"""
信頼スコア算出モジュール
S = 0.5×TC + 0.3×SC + 0.2×MS
"""
import difflib


def test_coverage_score(test_results: list[dict]) -> float:
    """
    TC：テスト網羅性スコア
    正常系・境界値・回帰の3種テストが通過したか（各+0.33）
    """
    checks = {
        "happy_path": any(
            r["passed"] for r in test_results if "happy_path" in r["name"]
        ),
        "edge_case": any(
            r["passed"] for r in test_results if "edge_case" in r["name"]
        ),
        "regression": any(
            r["passed"] for r in test_results if "regression" in r["name"]
        ),
    }
    return round(sum(checks.values()) / len(checks), 3)


def scope_score(original: str, modified: str, threshold: float = 0.20) -> float:
    """
    SC：修正範囲スコア
    変更行数/総行数を正規化。局所的なほど高スコア
    threshold: これ以上変更するとスコアが0になる割合（デフォルト20%）
    """
    diff = list(difflib.unified_diff(
        original.splitlines(),
        modified.splitlines()
    ))
    changed_lines = sum(
        1 for line in diff
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )
    total_lines = max(len(original.splitlines()), 1)
    ratio = changed_lines / total_lines
    return round(max(0.0, 1.0 - (ratio / threshold)), 3)


def memory_score(similarity: float | None) -> float:
    """
    MS：記憶類似度スコア
    Chromaのコサイン類似度をそのまま使用
    類似パターンがない場合（初回）は 0.0
    """
    if similarity is None:
        return 0.0
    return round(max(0.0, min(1.0, similarity)), 3)


def confidence_score(
    tc: float,
    sc: float,
    ms: float,
    w_tc: float = 0.5,
    w_sc: float = 0.3,
    w_ms: float = 0.2,
) -> float:
    """
    最終信頼スコア S = w_tc×TC + w_sc×SC + w_ms×MS
    重みは予備実験後に調整（論文に明示する）
    """
    score = w_tc * tc + w_sc * sc + w_ms * ms
    return round(score, 3)


def compute_all(
    test_results:   list[dict],
    original_code:  str,
    modified_code:  str,
    top_similarity: float | None,
) -> dict:
    """全スコアをまとめて算出して返す"""
    tc = test_coverage_score(test_results)
    sc = scope_score(original_code, modified_code)
    ms = memory_score(top_similarity)
    s  = confidence_score(tc, sc, ms)
    return {"TC": tc, "SC": sc, "MS": ms, "score": s}
