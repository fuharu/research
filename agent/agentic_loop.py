# -*- coding: utf-8 -*-
"""
②能動的情報収集（agentic）ループ ― ReAct方式（テキストプロトコル）
ソースは渡さない。read_file で原因ファイルを特定し apply_fix で直す。
失敗した apply は revert_fn で元のバグ状態へ戻し、各試行を汚染しない。
"""
import re
import time
from dataclasses import dataclass, field

import reflection_engine as RE   # _call_gemini / _extract_code を再利用

MAX_ITERS       = 14
TIMEOUT_SECONDS = 300
MAX_TOKENS      = 60_000
READ_LIMIT      = 8000   # 数百行までは実質全文（巨大ファイルはツール探索フェーズでpatch化）

ACTION_RE = re.compile(r"Action\s*:\s*([A-Za-z_]+)", re.I)
INPUT_RE  = re.compile(r"Action Input\s*:\s*(.+)", re.I)


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
    transcript:  str = ""


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


def _build_prompt(error_log, memory_hits, transcript, file_list):
    return f"""あなたは稼働中システムのバグを修復するエンジニアです。
実行時エラーが発生しました。ソースは渡されていません。ツールで原因ファイルを特定し修正してください。

【ツール】
- read_file : 指定ファイルの中身を読む（Action Input にパス1つ）
- apply_fix : 修正を適用しテスト実行（Action Input にバグのあるファイルのパス、本文に ```python ... ``` で修正後のファイル全体）

【発生したエラー】
{error_log}
{_memory_section(memory_hits)}
【候補ファイル（この中に原因がある）】
{file_list}

【これまでの行動と結果】
{transcript or "(まだ何もしていない)"}

【方針】
1) まず原因がありそうなファイルを read_file で読む（推測でいきなり apply_fix しない）
2) 原因を特定したら、そのファイルに対して apply_fix（既存のクラス/関数は残し、ファイル全体を出力）
3) テストが全通過で完了。失敗したらファイルは元のバグ状態に戻るので、読み直して別案を試す

【出力（1手だけ・厳守）】
Thought: <短い考え>
Action: read_file | apply_fix
Action Input: <パス>
（apply_fix のときは続けて ```python\n<修正後のファイル全体>\n``` を必ず付ける）
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
    transcript = ""
    file_list = "\n".join(f"- {p}" for p in sorted(readable))
    history = []

    def done(success, code, reason):
        return AgentResult(success, code, attempts, iters, reads,
                           round(time.perf_counter()-start, 3), tokens, reason, history, transcript)

    for _ in range(MAX_ITERS):
        if time.perf_counter() - start > TIMEOUT_SECONDS:
            return done(False, None, "timeout")
        if tokens >= MAX_TOKENS:
            return done(False, None, "cost_limit")

        prompt = _build_prompt(error_log, memory_hits, transcript, file_list)
        try:
            text, used = RE._call_gemini(prompt); tokens += used
        except Exception as e:
            transcript += f"\nObservation: LLM呼び出し失敗（{e}）\n"; iters += 1; continue
        iters += 1

        m = ACTION_RE.search(text); action = (m.group(1).lower() if m else "")
        mi = INPUT_RE.search(text);  arg = (mi.group(1).strip() if mi else "")

        if action == "read_file":
            tgt = _resolve(arg, readable)
            if not tgt:
                obs = f"そのパスは読めません。候補: {sorted(readable)}"
            else:
                reads += 1
                obs = f"--- {tgt} ---\n{read_file_fn(tgt)[:READ_LIMIT]}"
            history.append({"act": f"read_file {arg}", "obs": obs[:300]})
            transcript += f"\nAction: read_file {arg}\nObservation: {obs}\n"

        elif action == "apply_fix":
            tgt = _resolve(arg, writable); code = RE._extract_code(text)
            if not tgt:
                transcript += f"\nAction: apply_fix {arg}\nObservation: 書込不可。{sorted(writable)} のいずれかへ。\n"
                history.append({"act": f"apply_fix {arg}", "obs": "bad path"}); continue
            if not code:
                transcript += f"\nAction: apply_fix {tgt}\nObservation: ```python``` のコードブロックが必要です。\n"
                history.append({"act": f"apply_fix {tgt}", "obs": "no code"}); continue
            attempts += 1
            try:
                apply_fix_fn(tgt, code); tr = test_fn()
            except Exception as e:
                if revert_fn: revert_fn()
                transcript += f"\nApplied fix to {tgt} → 例外: {e}\n"
                history.append({"act": f"apply_fix {tgt}", "obs": f"exc {e}", "code": code[:300]}); continue
            if tr.get("all_passed"):
                history.append({"act": f"apply_fix {tgt}", "obs": "PASS", "code": code[:300]})
                return done(True, code, "success")
            failed = [r["name"] for r in tr.get("details", []) if not r["passed"]]
            if revert_fn: revert_fn()
            transcript += f"\nApplied fix to {tgt} → テスト失敗: {failed}（ファイルは元に戻した）\n"
            history.append({"act": f"apply_fix {tgt}", "obs": f"fail {failed}", "code": code[:300]})

        else:
            transcript += "\nObservation: 不正なAction。read_file か apply_fix を使ってください。\n"
            history.append({"act": "invalid", "obs": text[:120]})

    return done(False, None, "max_iters")
