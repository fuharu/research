# -*- coding: utf-8 -*-
"""
②能動的情報収集（agentic）ループ ― ReAct方式（テキストプロトコル）
================================================================
ソースコードは最初は渡さない。エージェントが自分で
  read_file(path)         … 候補ファイルの中身を読む
  apply_fix(path, code)   … 指定ファイルへ修正を適用しテスト実行
を呼びながら、原因ファイルを特定して直す。
LLM呼び出し・コード抽出は reflection_engine を再利用（provider非依存）。
"""
import re
import time
from dataclasses import dataclass, field

import reflection_engine as RE   # _call_gemini / _extract_code を再利用

MAX_ITERS       = 12
TIMEOUT_SECONDS = 300
MAX_TOKENS      = 60_000

ACTION_RE = re.compile(r"Action\s*:\s*([A-Za-z_]+)", re.I)
INPUT_RE  = re.compile(r"Action Input\s*:\s*(.+)", re.I)


@dataclass
class AgentResult:
    success:     bool
    fix_code:    str | None = None
    attempts:    int = 0      # apply_fix 呼び出し回数
    iters:       int = 0      # ツール呼び出し（LLMターン）総数
    reads:       int = 0      # read_file 回数
    latency:     float = 0.0
    tokens:      int = 0
    stop_reason: str | None = None
    history:     list = field(default_factory=list)


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
実行時エラーが発生しました。ソースコードは渡されていません。ツールで原因ファイルを自分で特定し、修正してください。

【利用できるツール】
- read_file   : 指定ファイルの中身を読む（Action Input にパス1つ）
- apply_fix   : 修正を適用してテスト実行（Action Input にパス、本文に ```python ... ``` で修正後のファイル全体）

【発生したエラー】
{error_log}
{_memory_section(memory_hits)}
【候補ファイル（この中に原因がある）】
{file_list}

【これまでの行動と結果】
{transcript or "(まだ何もしていない)"}

【手順の方針】
1) まず原因がありそうなファイルを read_file で読む（推測で apply_fix しない）
2) 原因を特定したら apply_fix でファイル全体を出力して適用する
3) テストが全て通れば完了

【出力形式（厳守・1手だけ）】
Thought: <短い考え>
Action: read_file | apply_fix
Action Input: <パス>
（apply_fix のときは続けて ```python\n<修正後のファイル全体>\n``` を必ず付ける）
""".strip()


def _resolve(path, allowed):
    """パス表記の揺れを吸収：完全一致 or 末尾一致で allowed の正規パスへ。"""
    path = (path or "").strip().strip("`'\"")
    if path in allowed:
        return path
    for a in allowed:
        if a.endswith(path) or a.endswith("/" + path) or path.endswith(a):
            return a
        if path.split("/")[-1] == a.split("/")[-1]:   # ファイル名一致
            return a
    return None


def run(error_log, memory_hits, readable, writable, read_file_fn, apply_fix_fn, test_fn):
    """
    readable/writable: 許可パスの集合
    read_file_fn(path)->str / apply_fix_fn(path, code)->None / test_fn()->dict
    """
    start = time.perf_counter()
    tokens = 0
    transcript = ""
    attempts = reads = iters = 0
    file_list = "\n".join(f"- {p}" for p in sorted(readable))
    history = []

    for _ in range(MAX_ITERS):
        elapsed = time.perf_counter() - start
        if elapsed > TIMEOUT_SECONDS:
            return AgentResult(False, None, attempts, iters, reads, round(elapsed,3), tokens, "timeout", history)
        if tokens >= MAX_TOKENS:
            return AgentResult(False, None, attempts, iters, reads, round(elapsed,3), tokens, "cost_limit", history)

        prompt = _build_prompt(error_log, memory_hits, transcript, file_list)
        try:
            text, used = RE._call_gemini(prompt)
            tokens += used
        except Exception as e:
            history.append({"act": "llm_error", "obs": str(e)})
            transcript += f"\nObservation: LLM呼び出し失敗（{e}）\n"
            iters += 1
            continue
        iters += 1

        m = ACTION_RE.search(text)
        action = (m.group(1).lower() if m else "")
        mi = INPUT_RE.search(text)
        arg = (mi.group(1).strip() if mi else "")

        if action == "read_file":
            tgt = _resolve(arg, readable)
            if not tgt:
                obs = f"そのパスは読めません。候補から選んでください: {sorted(readable)}"
            else:
                reads += 1
                content = read_file_fn(tgt)
                obs = f"--- {tgt} ---\n{content[:1400]}"
            history.append({"act": f"read_file {arg}", "obs": obs[:200]})
            transcript += f"\nAction: read_file {arg}\nObservation: {obs}\n"

        elif action == "apply_fix":
            tgt = _resolve(arg, writable)
            code = RE._extract_code(text)
            if not tgt:
                transcript += f"\nAction: apply_fix {arg}\nObservation: 書込不可のパス。{sorted(writable)} のいずれかへ。\n"
                history.append({"act": f"apply_fix {arg}", "obs": "bad path"})
                continue
            if not code:
                transcript += f"\nAction: apply_fix {tgt}\nObservation: ```python``` のコードブロックが見つかりません。修正後のファイル全体を付けてください。\n"
                history.append({"act": f"apply_fix {tgt}", "obs": "no code"})
                continue
            attempts += 1
            try:
                apply_fix_fn(tgt, code)
                tr = test_fn()
            except Exception as e:
                transcript += f"\nApplied fix to {tgt} → 例外: {e}\n"
                history.append({"act": f"apply_fix {tgt}", "obs": f"exc {e}"})
                continue
            if tr.get("all_passed"):
                return AgentResult(True, code, attempts, iters, reads,
                                   round(time.perf_counter()-start,3), tokens, "success", history)
            failed = [r["name"] for r in tr.get("details", []) if not r["passed"]]
            transcript += f"\nApplied fix to {tgt} → テスト失敗: {failed}\n"
            history.append({"act": f"apply_fix {tgt}", "obs": f"fail {failed}"})

        else:
            transcript += "\nObservation: 不正なAction。read_file か apply_fix を使ってください。\n"
            history.append({"act": "invalid", "obs": text[:120]})

    return AgentResult(False, None, attempts, iters, reads,
                       round(time.perf_counter()-start,3), tokens, "max_iters", history)
