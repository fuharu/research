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
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")   # .env で gemini-2.5-flash 等に変更可
GEMINI_URL     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


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

def _call_bedrock(prompt: str) -> tuple[str, int]:
    """Amazon Bedrock（Claude等）で生成。Throttling等は指数バックオフでリトライ。"""
    import boto3
    region   = os.getenv("AWS_REGION", "us-east-1")
    model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-haiku-20241022-v1:0")
    client   = boto3.client("bedrock-runtime", region_name=region)

    max_retries = 5
    base_wait   = 4.0
    for attempt in range(max_retries):
        try:
            resp = client.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 4096, "temperature": 1.0},
            )
            text   = resp["output"]["message"]["content"][0]["text"]
            tokens = resp.get("usage", {}).get("totalTokens", 500)
            return text, tokens
        except Exception as e:
            code = ""
            if isinstance(getattr(e, "response", None), dict):
                code = e.response.get("Error", {}).get("Code", "")
            transient = code in (
                "ThrottlingException", "TooManyRequestsException",
                "ServiceUnavailableException", "ModelTimeoutException",
                "InternalServerException",
            )
            if attempt < max_retries - 1 and transient:
                time.sleep(min(base_wait * (2 ** attempt), 60))
                continue
            raise


def _call_gemini(prompt: str) -> tuple[str, int]:
    """修復LLMを呼び出す（LLM_PROVIDER で gemini/bedrock を切替。mock 時はモックGemini）"""
    if os.getenv("LLM_PROVIDER", "gemini").lower() == "bedrock":
        return _call_bedrock(prompt)
    # 修復LLMはバックエンド(app)のモック設定とは独立に制御する。
    # REFLECTION_USE_MOCK が未設定/空なら USE_MOCK_GEMINI にフォールバック（後方互換）。
    use_mock = (os.getenv("REFLECTION_USE_MOCK") or os.getenv("USE_MOCK_GEMINI", "true")).lower() == "true"
    mock_url = os.getenv("MOCK_GEMINI_URL", "http://mock_gemini:9000")

    if use_mock:
        url = f"{mock_url}/v1beta/models/gemini-1.5-flash:generateContent"
        params = {}
    else:
        url = GEMINI_URL
        params = {"key": GEMINI_API_KEY}

    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    # 429（レート制限）/ 5xx（一時障害）は指数バックオフでリトライ。
    # Retry-After ヘッダがあれば優先。400/403 等は即時に例外を投げる。
    max_retries = 5
    base_wait   = 4.0
    resp = None
    for attempt in range(max_retries):
        resp = httpx.post(url, params=params, json=payload, timeout=60)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt < max_retries - 1:
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else base_wait * (2 ** attempt)
                time.sleep(min(wait, 60))
                continue
        break

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
    source_code: str | None = None,
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

    source_section = ""
    if source_code:
        source_section = f"""
【修正対象ファイルの現在のコード（このファイルを修正する。勝手に別物へ作り変えない）】
```python
{source_code}
```
"""

    return f"""
あなたはソフトウェアエンジニアです。以下の実行時エラーを修正するPythonコードを生成してください。

【発生したエラー】
{error_log}
{source_section}{memory_section}
{history_section}

【指示】
1. エラーの根本原因を1文で説明してください
2. 修正方針を1文で説明してください
3. 【重要】上記「現在のコード」を最小限だけ直し、修正後のファイル全体を出力してください
4. クラス名・関数名・エンドポイント等の既存構造は維持し、import から始まる完全なPythonファイルを出力してください（```python ``` で囲む）
5. 過去の失敗アプローチは絶対に繰り返さないでください
""".strip()


# ── メインループ ──────────────────────────────

def run(
    error_log:   str,
    memory_hits: list[dict],
    apply_fix_fn,    # サンドボックスで修正を適用してテストする関数
    test_fn,         # 事前定義テストを実行する関数
    source_code: str | None = None,   # 修正対象ファイルの現在のコード（バグ入り）
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
        prompt = _build_prompt(error_log, memory_hits, history, source_code)
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

        # ── サンドボックスで適用・テスト ─────