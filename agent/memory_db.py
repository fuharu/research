"""
エピソード記憶データベース（Chroma）
成功・失敗パターンを保存し、類似エラー発生時に参照する

埋め込みモデル：環境変数で固定（実験期間中は変更しない）
  EMBEDDING_MODEL   = models/gemini-embedding-001
  EMBEDDING_VERSION = 20250301
"""
import os
import time
import chromadb
from chromadb.utils import embedding_functions

# 埋め込みプロバイダ：gemini | bedrock（未設定なら LLM_PROVIDER → gemini にフォールバック）
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", os.getenv("LLM_PROVIDER", "gemini")).lower()
EMBEDDING_MODEL   = os.getenv("EMBEDDING_MODEL",   "models/gemini-embedding-001")
EMBEDDING_VERSION = os.getenv("EMBEDDING_VERSION", "20250301")
SIMILARITY_THRESHOLD = 0.60   # 較正値: 兄弟0.84 / 別種≤0.32 の谷(diag_threshold.py)。旧0.75は高すぎ
DB_PATH = "/results/memory_db"

# ── 初期化 ───────────────────────────────────

def _get_embedding_function():
    """プロバイダに応じた埋め込み関数を返す。"""
    if EMBEDDING_PROVIDER == "bedrock":
        import boto3
        session = boto3.Session(region_name=os.getenv("AWS_REGION", "us-east-1"))
        return embedding_functions.AmazonBedrockEmbeddingFunction(
            session=session,
            model_name=os.getenv("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0"),
        )
    return embedding_functions.GoogleGenerativeAiEmbeddingFunction(
        api_key=os.getenv("GEMINI_API_KEY"),
        model_name=EMBEDDING_MODEL,
    )


def _get_collection():
    client = chromadb.PersistentClient(path=DB_PATH)
    ef = _get_embedding_function()
    # プロバイダ＋バージョンでコレクションを分離（次元の異なるベクトルの混在を防ぐ）
    collection_name = f"episode_memory_{EMBEDDING_PROVIDER}_{EMBEDDING_VERSION}"
    # 距離を【コサイン】に固定する（重要）。
    #   Chroma の既定は L2（ユークリッド）距離。search_similar は similarity = 1 - dist と
    #   していてコサインを前提にしているため、L2 のままだと「ほぼ同一」でも distance が 0.3 前後
    #   になり 1-0.3=0.7 < 0.75 で弾かれる（＝似た事例を拾えない）。cosine にすると
    #   distance = 1 - cos となり、似た事例ほど similarity が 0.9 前後で正しく拾える。
    #   注：space はコレクション作成時にのみ決定される。既存(L2)コレクションがあると
    #   get_or_create はそれを返すので、results/memory_db を消すか EMBEDDING_VERSION を
    #   上げて作り直すこと。
    return client.get_or_create_collection(
        name=collection_name,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


# ── 保存 ─────────────────────────────────────

def save_success(error_log: str, fix_code: str, scenario: str, attempts: int):
    """成功パターンを保存"""
    collection = _get_collection()
    collection.add(
        documents=[error_log],
        metadatas=[{
            "fix_code":  fix_code,
            "scenario":  scenario,
            "result":    "success",
            "attempts":  str(attempts),
            "timestamp": str(time.time()),
        }],
        ids=[f"ep_{int(time.time() * 1000)}"],
    )


def save_failure(error_log: str, tried_fixes: list, reason: str, scenario: str):
    """失敗パターンを保存（負の知識として活用）"""
    collection = _get_collection()
    collection.add(
        documents=[error_log],
        metadatas=[{
            "tried_fixes": str(tried_fixes),
            "reason":      reason,
            "scenario":    scenario,
            "result":      "failure",
            "timestamp":   str(time.time()),
        }],
        ids=[f"ep_{int(time.time() * 1000)}"],
    )


# ── 検索 ─────────────────────────────────────

def search_similar(error_log: str, n: int = 3) -> list[dict]:
    """
    類似エラーを検索する
    コサイン類似度 ≥ SIMILARITY_THRESHOLD のものだけ返す
    閾値未満の場合は空リストを返す（MS = 0.0 として扱う）
    """
    collection = _get_collection()
    count = collection.count()
    if count == 0:
        return []

    results = collection.query(
        query_texts=[error_log],
        n_results=min(n, count),
        include=["documents", "metadatas", "distances"],
    )

    relevant = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        similarity = 1.0 - dist   # コサイン距離 → 類似度
        if similarity >= SIMILARITY_THRESHOLD:
            relevant.append({
                "error_log":  doc,
                "metadata":   meta,
                "similarity": round(similarity, 3),
            })

    return relevant


def get_top_similarity(error_log: str) -> float | None:
    """MS スコア計算用：最高類似度を返す（なければ None）"""
    results = search_similar(error_log, n=1)
    if not results:
        return None
    return results[0]["similarity"]


def reset():
    """実験条件をリセットする（試行の独立性確保のため）"""
    collection = _get_collection()
    ids = collection.get()["ids"]
    if ids:
        collection.delete(ids=ids)
