"""
リフレクション（自己内省）エンジン
失敗履歴を踏まえて修正アプローチを変えるループを実装する

停止条件（3トリガー）：
  ① 試行回数 ≥ MAX_ATTEMPTS（5回）
  ② 経過時間 ≥ TIMEOUT_SECONDS（300秒）
  ③ LLMトークン ≥ MAX_TOKENS（50,000）
"""
import os
import time
import httpx
from dataclasses import dataclass, field

MAX_ATTEMPTS    = 5
TIMEOUT_SECONDS = 300
MAX_TOKENS      = 50_000

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL     = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


@dataclass
class LoopResult:
    success:   bool
    fix_code:  str | None      = None
    attempts:  int             = 0
    latency:   float           = 0.0
    tokens:    int             = 0
    stop_reason: str | None    = None   # "success" / "max_attempts" / "timeout" / "cost_limit"
    history:   list[dict]      = field(default_factory=list)


# ── LLM呼び出し ──────────────────────────────

def _call_gemini(prompt: str) -> tuple[str, int]:
    """Gemini APIを呼び出す（USE_MOCK_GEMINI=true の場合はモックを使用）"""
    use_mock = os.getenv("USE_MOCK_GEMINI", "true").lower() == "true"
    mock_url = os.getenv("MOCK_GEMINI_URL", "http://mock_gemini:9000")

    if use_mock:
        url = f"{mock_url}/v1beta/models/gemini-1.5-flash:generateContent"
        resp = httpx.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=60,
        )
    else:
        resp = httpx.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=60,
        )
    resp.raise_for_status()
    data = resp.json()
    text   = data["candidates"][0]["content"]["parts"][0]["text"]
    tokens = data.get("usageMetadata", {}).get("totalTokenCount", 500)
    return text, tokens


# ── プロンプト生成 ────────────────────────────

def _build_prompt(
    error_log:   str,
    memory_hits: list[dict],
    history:     list[dict],
) -> str:
    """失敗履歴と記憶DBの参照情報を組み込んだプロンプトを生成する"""

    memory_section = ""
    if memory_hits:
        success_hits = [h for h in memory_hits if h["metadata"].get("result") == "success"]
        failure_hits = [h for h in memory_hits if h["metadata"].get("result") == "failure"]

        if success_hits:
            best = success_hits[0]
            memory_section += f"""
【記憶DBより：類似エラーの成功事例（類似度 {best['similarity']}）】
過去のエラー: {best['error_log'][:200]}
成功した修正: {best['metadata'].get('fix_code', '')[:300]}
"""
        if failure_hits:
            memory_section += "\n【記憶DBより：過去に失敗したアプローチ（参考：これは避けること）】\n"
            for h in failure_hits[:2]:
                memory_section += f"- {h['metadata'].get('tried_fixes', '')[:200]}\n"

    history_section = ""
    if history:
        history_section = "\n【これまでの試みと失敗理由（同じアプローチは繰り返さないこと）】\n"
        for i, h in enumerate(history, 1):
            history_section += f"試み{i}: {h.get('fix_summary', '')}  → 失敗理由: {h.get('error', '')}\n"

    return f"""
あなたはソフトウェアエンジニアです。以下の実行時エラーを修正するPythonコードを生成してください。

【発生したエラー】
{error_log}
{memory_section}
{history_section}

【指示】
1. エラーの根本原因を1文で説明してください
2. 修正方針を1文で説明してください
3. 【重要】修正後のファイル全体のコードを出力してください
4. スニペットではなく、importから始まる完全なPythonファイルとして出力してください（```python ``` で囲む）
5. 過去の失敗アプローチは絶対に繰り返さないでください
""".strip()


# ── メインループ ──────────────────────────────

def run(
    error_log:   str,
    memory_hits: list[dict],
    apply_fix_fn,    # サンドボックスで修正を適用してテストする関数
    test_fn,         # 事前定義テストを実行する関数
) -> LoopResult:
    """
    リフレクションループを実行する

    Args:
        error_log:   スタックトレース等のエラーログ
        memory_hits: 記憶DBからの類似パターン
        apply_fix_fn: (fix_code: str) → bool  サンドボックスで適用
        test_fn:      () → dict               事前定義テストを実行
    """
    start   = time.perf_counter()
    tokens  = 0
    history = []

    for attempt in range(MAX_ATTEMPTS):

        # ── 停止トリガー② タイムアウト ──────────
        elapsed = time.perf_counter() - start
        if elapsed > TIMEOUT_SECONDS:
            return LoopResult(
                success=False, attempts=attempt,
                latency=elapsed, tokens=tokens,
                stop_reason="timeout", history=history,
            )

        # ── 停止トリガー③ トークン上限 ──────────
        if tokens >= MAX_TOKENS:
            return LoopResult(
                success=False, attempts=attempt,
                latency=elapsed, tokens=tokens,
                stop_reason="cost_limit", history=history,
            )

        # ── 修正案生成 ───────────────────────────
        prompt = _build_prompt(error_log, memory_hits, history)
        try:
            response_text, used_tokens = _call_gemini(prompt)
            tokens += used_tokens
        except Exception as e:
            history.append({"fix_summary": "LLM呼び出し失敗", "error": str(e)})
            continue

        # コードブロックを抽出
        fix_code = _extract_code(response_text)
        if not fix_code:
            history.append({"fix_summary": "コード抽出失敗", "error": "コードブロックが見つからない"})
            continue

        # ── サンドボックスで適用・テスト ─────────
        try:
            apply_fix_fn(fix_code)
            test_result = test_fn()
        except Exception as e:
            history.append({"fix_summary": fix_code[:100], "error": str(e)})
            continue

        # ── 正常停止 ─────────────────────────────
        if test_result.get("all_passed"):
            return LoopResult(
                success=True,
                fix_code=fix_code,
                attempts=attempt + 1,
                latency=round(time.perf_counter() - start, 3),
                tokens=tokens,
                stop_reason="success",
                history=history,
            )

        # テスト失敗 → 履歴に追記してループ継続
        failed = [r for r in test_result.get("details", []) if not r["passed"]]
        history.append({
            "fix_summary": fix_code[:100],
            "error": f"テスト失敗: {[r['name'] for r in failed]}",
        })

    # ── 停止トリガー① 試行回数上限 ──────────────
    return LoopResult(
        success=False,
        attempts=MAX_ATTEMPTS,
        latency=round(time.perf_counter() - start, 3),
        tokens=tokens,
        stop_reason="max_attempts",
        history=history,
    )


def _extract_code(text: str) -> str | None:
    """LLMの出力からコードブロックを抽出する"""
    import re
    match = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None
