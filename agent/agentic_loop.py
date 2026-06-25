# -*- coding: utf-8 -*-
"""
②能動的情報収集（agentic）ループ ― ReAct方式。
ソースは渡さず、エージェントがツールで原因を特定し patch編集で直す。

大規模ファイル（数千行）対応の情報収集ツール：
- read_file       : ファイルを読む。小さいファイルは全文（行番号付き）、大きいファイルは
                    アウトライン（def/class の一覧＋行番号）を返す＝「地図」。
- search_in_file  : ファイル内をキーワード検索（grep）。一致行を行番号付きで返す。
- read_lines      : 指定した行範囲だけを読む（行番号付き）。
修正ツール：
- edit_file       : 既存コードの一部を SEARCH/REPLACE で置換（主ツール）。
- apply_fix       : ファイル全体を書き換え（小さいファイル向け代替）。
プロンプトには「直近1観測」＋「短い行動ログ」だけを載せ、トークン肥大を防ぐ。
失敗した適用は revert_fn で元のバグ状態へ戻す（試行の独立性）。
"""
import re
import time
from dataclasses import dataclass, field

import reflection_engine as RE   # _call_gemini / _extract_code を再利用

MAX_ITERS       = 18
TIMEOUT_SECONDS = 420
MAX_TOKENS      = 120_000
READ_LIMIT      = 12000   # 1観測あたりの文字上限（トークン保護）
OUTLINE_OVER_LINES = 200  # これを超える行数のファイルは read_file でアウトライン化
SEARCH_MAX_HITS = 25
READ_LINES_MAX  = 160     # read_lines の最大スパン

ACTION_RE = re.compile(r"Action\s*:\s*([A-Za-z_]+)", re.I)
INPUT_RE  = re.compile(r"Action Input\s*:\s*(.+)", re.I)
RANGE_RE  = re.compile(r"(\d+)\s*[-:]\s*(\d+)")

# SEARCH/REPLACE ブロック（複数可）。前後の空白に寛容。
SR_RE = re.compile(
    r"<<<<<<<\s*SEARCH\s*\n(.*?)\n?=======\s*\n(.*?)\n?>>>>>>>\s*REPLACE",
    re.S,
)
# アウトライン抽出（関数・クラス・メソッド定義）
DEF_RE = re.compile(r"^\s*(async\s+def|def|class)\s+\w+")


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


# ── ファイル内ナビゲーション ────────────────────

def _number(lines, start=1):
    """行番号付きテキスト（start から）。lines は行のリスト。"""
    return "\n".join(f"L{start+i}: {ln}" for i, ln in enumerate(lines))


def _outline(content: str) -> str:
    """def/class の一覧（行番号付き）。大規模ファイルの地図。"""
    lines = content.splitlines()
    hits = [f"L{i+1}: {ln.rstrip()}" for i, ln in enumerate(lines) if DEF_RE.match(ln)]
    head = (f"（{len(lines)}行の大きいファイル。アウトラインのみ表示。"
            f"search_in_file で該当箇所を探し、read_lines で範囲を読むこと）\n")
    return head + "\n".join(hits[:400])


def _grep(content: str, query: str) -> str:
    """query を含む行を行番号付きで返す（最大 SEARCH_MAX_HITS 件）。"""
    q = query.strip().lower()
    if not q:
        return "（検索語が空）"
    lines = content.splitlines()
    hits = [f"L{i+1}: {ln.rstrip()}" for i, ln in enumerate(lines) if q in ln.lower()]
    if not hits:
        return f"（'{query}' に一致なし）"
    more = "" if len(hits) <= SEARCH_MAX_HITS else f"\n…他 {len(hits)-SEARCH_MAX_HITS} 件"
    return "\n".join(hits[:SEARCH_MAX_HITS]) + more


def _slice(content: str, a: int, b: int) -> str:
    """a..b 行（1始まり・両端含む）を行番号付きで返す。"""
    lines = content.splitlines()
    a = max(1, a); b = min(len(lines), b)
    if a > b:
        return "（行範囲が不正）"
    if b - a + 1 > READ_LINES_MAX:
        b = a + READ_LINES_MAX - 1
    return _number(lines[a-1:b], start=a)


def _read_observation(content: str) -> str:
    """read_file の結果：小ファイルは全文（行番号付き）、大ファイルはアウトライン。"""
    lines = content.splitlines()
    if len(lines) <= OUTLINE_OVER_LINES:
        return _number(lines, start=1)
    return _outline(content)


# ── patch編集（SEARCH/REPLACE）ユーティリティ ──────────────

def _parse_edits(text: str):
    return [(m.group(1), m.group(2)) for m in SR_RE.finditer(text)]


def _flexible_pattern(search: str) -> str:
    parts = search.split()
    return r"\s+".join(re.escape(p) for p in parts)


def _apply_edits(content: str, edits):
    applied = 0
    for search, replace in edits:
        if search.strip() == "":
            return None, "空のSEARCHブロック"
        idx = content.find(search)
        if idx != -1:
            content = content[:idx] + replace + content[idx + len(search):]
            applied += 1
            continue
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
            f"そのとき効いた修正の例:\n{b['metadata'].get('fix_code','')[:400]}\n"
            f"（ヒント：似た箇所・手法を手がかりにすること）\n")


def _build_prompt(error_log, memory_hits, actions, last_obs, file_list):
    log = "\n".join(actions[-10:]) or "(まだ何もしていない)"
    if last_obs:
        obs = f"\n【直近の観測：{last_obs[0]}】\n```\n{last_obs[1]}\n```\n"
    else:
        obs = "\n（まだ何も読んでいない）\n"
    return f"""あなたは稼働中システムのバグを修復するエンジニアです。
実行時エラーが発生しました。ソースは渡されていません。ツールで原因を特定し修正してください。

【ツール】
- read_file       : ファイルを読む（小=全文／大=アウトライン）。Action Input にパス1つ
- search_in_file  : ファイル内をキーワード検索。Action Input に「パス 検索語」
- read_lines      : 指定行範囲を読む。Action Input に「パス 開始-終了」（例: black.py 390-410）
- edit_file       : 一部を置換して修正（主ツール）。Action Input に対象パス、本文に
                    SEARCH/REPLACE ブロック（複数可）。SEARCH は実在コードを“そのまま”。
                    ※行番号の "Lnnn: " は付けないこと（コード本体のみ）。
- apply_fix       : ファイル全体を書換（小ファイル向け）。Action Input にパス、本文に ```python 全体```

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
{obs}
【方針】
1) まず read_file でアウトライン把握 → search_in_file で該当箇所を特定 → read_lines で周辺を読む
2) 原因が分かったら edit_file で“最小限の置換”を行う（whole-file は避ける）
3) テスト全通過で完了。失敗時はファイルは元に戻るので読み直して別案を試す

【出力（1手だけ・厳守）】
Thought: <短い考え>
Action: read_file | search_in_file | read_lines | edit_file | apply_fix
Action Input: <上の各ツールの形式で>
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
    last_obs = None
    file_list = "\n".join(f"- {p}" for p in sorted(readable))

    def done(success, code, reason):
        return AgentResult(success, code, attempts, iters, reads,
                           round(time.perf_counter()-start, 3), tokens, reason, actions)

    def _try_write(tgt, new_content):
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

        prompt = _build_prompt(error_log, memory_hits, actions, last_obs, file_list)
        try:
            text, used = RE._call_gemini(prompt); tokens += used
        except Exception as e:
            actions.append(f"LLM呼び出し失敗（{e}）"); iters += 1; continue
        iters += 1

        m = ACTION_RE.search(text); action = (m.group(1).lower() if m else "")
        mi = INPUT_RE.search(text);  arg = (mi.group(1).strip() if mi else "")
        parts = arg.split(None, 1)
        path_tok = parts[0] if parts else ""
        rest = parts[1] if len(parts) > 1 else ""

        if action == "read_file":
            tgt = _resolve(path_tok, readable)
            if not tgt:
                actions.append(f"read_file {arg} → 不可（候補から選ぶ）")
            else:
                reads += 1
                content = read_file_fn(tgt)
                last_obs = (f"read_file {tgt}", _read_observation(content)[:READ_LIMIT])
                actions.append(f"read_file {tgt} → {content.count(chr(10))+1}行")

        elif action == "search_in_file":
            tgt = _resolve(path_tok, readable)
            if not tgt:
                actions.append(f"search_in_file {arg} → ファイル不可")
            elif not rest.strip():
                actions.append(f"search_in_file {tgt} → 検索語なし")
            else:
                reads += 1
                content = read_file_fn(tgt)
                last_obs = (f"search '{rest.strip()}' in {tgt}", _grep(content, rest)[:READ_LIMIT])
                actions.append(f"search_in_file {tgt} '{rest.strip()[:30]}'")

        elif action == "read_lines":
            tgt = _resolve(path_tok, readable)
            rng = RANGE_RE.search(arg)
            if not tgt:
                actions.append(f"read_lines {arg} → ファイル不可")
            elif not rng:
                actions.append(f"read_lines {tgt} → 行範囲（開始-終了）が必要")
            else:
                reads += 1
                a, b = int(rng.group(1)), int(rng.group(2))
                content = read_file_fn(tgt)
                last_obs = (f"read_lines {tgt} {a}-{b}", _slice(content, a, b)[:READ_LIMIT])
                actions.append(f"read_lines {tgt} {a}-{b}")

        elif action == "edit_file":
            tgt = _resolve(path_tok, writable)
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
            status, info = _try_write(tgt, new_content)
            if status == "pass":
                actions.append(f"edit_file {tgt} → PASS")
                return done(True, new_content, "success")
            actions.append(f"edit_file {tgt} → {'例外 '+info if status=='error' else '失敗 '+str(info)}")

        elif action == "apply_fix":
            tgt = _resolve(path_tok, writable); code = RE._extract_code(text)
            if not tgt:
                actions.append(f"apply_fix {arg} → 書込不可パス"); continue
            if not code:
                actions.append(f"apply_fix {tgt} → コードブロック無し"); continue
            attempts += 1
            status, info = _try_write(tgt, code)
            if status == "pass":
                actions.append(f"apply_fix {tgt} → PASS")
                return done(True, code, "success")
            actions.append(f"apply_fix {tgt} → {'例外 '+info if status=='error' else '失敗 '+str(info)}")

        else:
            actions.append("不正なAction（read_file/search_in_file/read_lines/edit_file/apply_fix）")

    return done(False, None, "max_iters")
