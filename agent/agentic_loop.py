# -*- coding: utf-8 -*-
"""
②能動的情報収集（agentic）ループ ― ReAct方式。
ソースは渡さず read_file で原因ファイルを特定し、patch編集（SEARCH/REPLACE）で直す。
トークン肥大を防ぐため、プロンプトには「直近に読んだ1ファイルの中身」＋
「短い行動ログ」だけを載せる（過去に読んだ全文は貯めない）。

修正ツールは2つ：
- edit_file  : 既存コードの一部を SEARCH/REPLACE で置換（主ツール。大きいファイルでも
               差分だけ出せばよく、whole-file 出力のトークン肥大と整形差を避けられる）。
- apply_fix  : ファイル全体を書き換え（小さいファイル向けのフォールバック）。
失敗した適用は revert_fn で元のバグ状態へ戻す（試行の独立性を保つ）。
"""
import re
import time
from dataclasses import dataclass, field

import reflection_engine as RE   # _call_gemini / _extract_code を再利用

MAX_ITERS       = 14
TIMEOUT_SECONDS = 300
MAX_TOKENS      = 60_000
READ_LIMIT      = 8000   # 直近1ファイルのみ全文（数百行まで）

ACTION_RE = re.compile(r"Action\s*:\s*([A-Za-z_]+)", re.I)
INPUT_RE  = re.compile(r"Action Input\s*:\s*(.+)", re.I)

# SEARCH/REPLACE ブロック（複数可）。前後の空白に寛容。
SR_RE = re.compile(
    r"<<<<<<<\s*SEARCH\s*\n(.*?)\n?=======\s*\n(.*?)\n?>>>>>>>\s*REPLACE",
    re.S,
)


@dataclass
class AgentResult:
    success:     bool
    fix_code:    str | None = None
    attempts:    int = 0
    iters:       int = 0
    reads:       int = 0
    latency:     float = 0.0
    tokens:      int = 0
    stop_reason: str | None = None
    history:     list = field(default_factory=list)


# ── patch編集（SEARCH/REPLACE）ユーティリティ ──────────────

def _parse_edits(text: str):
    """テキストから (search, replace) ブロックを全て抽出。"""
    return [(m.group(1), m.group(2)) for m in SR_RE.finditer(text)]


def _flexible_pattern(search: str) -> str:
    """空白量の違いを吸収して SEARCH 箇所を見つけるための緩いパターン。"""
    parts = search.split()
    return r"\s+".join(re.escape(p) for p in parts)


def _apply_edits(content: str, edits):
    """edits を順に適用。1ブロックでも当てられなければ (None, 理由)。
    完全一致を優先し、外したら空白寛容な一致でフォールバック。"""
    applied = 0
    for search, replace in edits:
        if search.strip() == "":
            return None, "空のSEARCHブロック"
        idx = content.find(search)
        if idx != -1:
            content = content[:idx] + replace + content[idx + len(search):]
            applied += 1
            continue
        # フォールバック：空白量を無視して箇所を特定
        m = re.search(_flexible_pattern(search), content)
        if m:
            content = content[:m.start()] + replace + content[m.end():]
            applied += 1
            continue
        return None, f"SEARCH不一致: {search.strip()[:60]!r}"
    if applied == 0:
        return None, "適用可能なブロックなし"
    return content, None


def _memory_section(memory_hits):
    if not memory_hits:
        return ""
    sh = [h for h in memory_hits if h["metadata"].get("result") == "success"]
    if not sh:
        return ""
    b = sh[0]
    return (f"\n【記憶DB：類似エラーの成功事例（類似度 {b['similarity']}）】\n"
            f"過去のエラー: {b['error_log'][:160]}\n"
            f"そのとき効いた修正の例:\n{b['metadata'].get('fix_code','')[:320]}\n"
            f"（ヒント：似た箇所・手法を手がかりにすること）\n")


def _build_prompt(error_log, memory_hits, actions, last_read, file_list):
    log = "\n".join(actions[-10:]) or "(まだ何もしていない)"
    if last_read:
        lr = f"\n【直近に読んだファイル：{last_read[0]}】\n```python\n{last_read[1]}\n```\n"
    else:
        lr = "\n（まだファイルを読んでいない）\n"
    return f"""あなたは稼働中システムのバグを修復するエンジニアです。
実行時エラーが発生しました。ソースは渡されていません。ツールで原因ファイルを特定し修正してください。

【ツール】
- read_file : 指定ファイルを読む（Action Input にパス1つ）
- edit_file : 既存コードの一部だけを置換して修正（主ツール）。Action Input に対象パス、
              本文に SEARCH/REPLACE ブロックを書く（複数可）。SEARCH には「直近に読んだ
              ファイル」に実在する行を“そのまま”コピーすること。
- apply_fix : ファイル全体を書き換え（小さいファイル向けの代替）。Action Input にパス、
              本文に ```python ...``` で修正後のファイル全体。

【edit_file の本文フォーマット（厳守）】
<<<<<<< SEARCH
（置換したい既存コードを正確にそのまま）
=======
（置換後のコード）
>>>>>>> REPLACE

【発生したエラー】
{error_log}
{_memory_section(memory_hits)}
【候補ファイル（この中に原因がある）】
{file_list}

【行動ログ】
{log}
{lr}
【方針】
1) 原因がありそうなファイルを read_file（推測でいきなり編集しない）
2) 原因を特定したら edit_file で“最小限の置換”を行う（whole-file は避ける）
3) 何度か読んだら、最も疑わしいファイルに必ず修正を試すこと
4) テスト全通過で完了。失敗時はファイルは元に戻るので読み直して別案を試す

【出力（1手だけ・厳守）】
Thought: <短い考え>
Action: read_file | edit_file | apply_fix
Action Input: <パス>
（edit_file は続けて SEARCH/REPLACE ブロックを、apply_fix は ```python 全体``` を必ず付ける）
""".strip()


def _resolve(path, allowed):
    path = (path or "").strip().strip("`'\"")
    if path in allowed:
        return path
    for a in allowed:
        if a.endswith(path) or a.endswith("/" + path) or path.endswith(a):
            return a
        if path.split("/")[-1] == a.split("/")[-1]:
            return a
    return None


def run(error_log, memory_hits, readable, writable,
        read_file_fn, apply_fix_fn, test_fn, revert_fn=None):
    start = time.perf_counter()
    tokens = attempts = reads = iters = 0
    actions = []
    last_read = None
    file_list = "\n".join(f"- {p}" for p in sorted(readable))

    def done(success, code, reason):
        return AgentResult(success, code, attempts, iters, reads,
                           round(time.perf_counter()-start, 3), tokens, reason, actions)

    def _try_write(tgt, new_content, label):
        """書込→テスト→（失敗なら revert）。戻り値: ("pass"|"fail"|"error", info)"""
        try:
            apply_fix_fn(tgt, new_content); tr = test_fn()
        except Exception as e:
            if revert_fn: revert_fn()
            return "error", str(e)
        if tr.get("all_passed"):
            return "pass", None
        failed = [r["name"] for r in tr.get("details", []) if not r["passed"]]
        if revert_fn: revert_fn()
        return "fail", failed

    for _ in range(MAX_ITERS):
        if time.perf_counter() - start > TIMEOUT_SECONDS:
            return done(False, None, "timeout")
        if tokens >= MAX_TOKENS:
            return done(False, None, "cost_limit")

        prompt = _build_prompt(error_log, memory_hits, actions, last_read, file_list)
        try:
            text, used = RE._call_gemini(prompt); tokens += used
        except Exception as e:
            actions.append(f"LLM呼び出し失敗（{e}）"); iters += 1; continue
        iters += 1

        m = ACTION_RE.search(text); action = (m.group(1).lower() if m else "")
        mi = INPUT_RE.search(text);  arg = (mi.group(1).strip() if mi else "")

        if action == "read_file":
            tgt = _resolve(arg, readable)
            if not tgt:
                actions.append(f"read_file {arg} → 不可（候補から選ぶ）")
            else:
                reads += 1
                content = read_file_fn(tgt)
                last_read = (tgt, content[:READ_LIMIT])
                actions.append(f"read_file {tgt} → {content.count(chr(10))+1}行 読了")

        elif action == "edit_file":
            tgt = _resolve(arg, writable)
            if not tgt:
                actions.append(f"edit_file {arg} → 書込不可パス"); continue
            edits = _parse_edits(text)
            if not edits:
                actions.append(f"edit_file {tgt} → SEARCH/REPLACEブロック無し"); continue
            current = read_file_fn(tgt)
            new_content, err = _apply_edits(current, edits)
            if err:
                actions.append(f"edit_file {tgt} → {err}"); continue
            attempts += 1
            status, info = _try_write(tgt, new_content, "edit_file")
            if status == "pass":
                actions.append(f"edit_file {tgt} → PASS")
                return done(True, new_content, "success")
            elif status == "error":
                actions.append(f"edit_file {tgt} → 例外 {info}")
            else:
                actions.append(f"edit_file {tgt} → 失敗 {info}")

        elif action == "apply_fix":
            tgt = _resolve(arg, writable); code = RE._extract_code(text)
            if not tgt:
                actions.append(f"apply_fix {arg} → 書込不可パス"); continue
            if not code:
                actions.append(f"apply_fix {tgt} → コードブロック無し"); continue
            attempts += 1
            status, info = _try_write(tgt, code, "apply_fix")
            if status == "pass":
                actions.append(f"apply_fix {tgt} → PASS")
                return done(True, code, "success")
            elif status == "error":
                actions.append(f"apply_fix {tgt} → 例外 {info}")
            else:
                actions.append(f"apply_fix {tgt} → 失敗 {info}")

        else:
            actions.append("不正なAction（read_file/edit_file/apply_fix のみ）")

    return done(False, None, "max_iters")
