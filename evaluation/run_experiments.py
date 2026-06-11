"""
実験自動実行スクリプト
360実験（6シナリオ × 3条件 × 20試行）を自動で実行し
結果をCSVに保存する

実行方法：
  python run_experiments.py
  python run_experiments.py --scenario L1-A --condition proposed --trials 5  # 部分実行
"""
import csv
import time
import argparse
from pathlib import Path
from datetime import datetime

import sys
sys.path.append("/agent")
sys.path.append("/evaluation")

from inject_bug       import inject, restore
from predefined_tests import run_all_tests
import memory_db
import reflection_engine
from confidence_score import compute_all

SCENARIOS  = ["L1-A", "L1-B", "L1-C", "L2-A", "L2-B", "L2-C"]
CONDITIONS = ["bl0", "bl1", "proposed"]
N_TRIALS   = 20
RESULTS_DIR = Path("/results")
THRESHOLD   = 0.85   # 暫定。ROC分析後に更新する
ALLOWED_FILES = {
    "L1-A": "/app/routers/tasks.py",
    "L1-B": "/app/routers/tasks.py",
    "L1-C": "/app/routers/tasks.py",
    "L2-A": "/app/schemas/task.py",
    "L2-B": "/app/routers/tasks.py",
    "L2-C": "/app/routers/tasks.py",
}

# ── 各条件の実装 ──────────────────────────────

def run_bl0(scenario: str, error_log: str) -> dict:
    """BL0：エラーログをそのままGemini APIへ渡すだけ"""
    import httpx, os
    start = time.perf_counter()
    try:
        resp = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={os.getenv('GEMINI_API_KEY')}",
            json={"contents": [{"parts": [{"text": f"このエラーを修正してください：{error_log}"}]}]},
            timeout=60,
        )
        resp.raise_for_status()
        success = True
    except Exception:
        success = False

    return {
        "success": success,
        "latency": round(time.perf_counter() - start, 3),
        "attempts": 1,
        "stop_reason": "success" if success else "error",
    }


def run_bl1(scenario: str, error_log: str) -> dict:
    """BL1：リフレクションあり・記憶DBなし"""
    result = reflection_engine.run(
        error_log=error_log,
        memory_hits=[],   # 記憶なし
        apply_fix_fn=lambda code: _apply_fix(scenario, code),
        test_fn=lambda: run_all_tests(scenario),
    )
    return _loop_result_to_dict(result)


def run_proposed(scenario: str, error_log: str, trial_num: int) -> dict:
    """提案手法：リフレクション＋記憶DB"""
    # 試行1回目のみ記憶DBをリセット（独立性の確保）
    # 2回目以降は蓄積を維持（記憶DB効果の測定）
    if trial_num == 1:
        memory_db.reset()

    memory_hits    = memory_db.search_similar(error_log)
    top_similarity = memory_db.get_top_similarity(error_log)

    result = reflection_engine.run(
        error_log=error_log,
        memory_hits=memory_hits,
        apply_fix_fn=lambda code: _apply_fix(scenario, code),
        test_fn=lambda: run_all_tests(scenario),
    )

    # 信頼スコアを算出
    test_result = run_all_tests(scenario)
    cs = compute_all(
        test_results=test_result.get("details", []),
        original_code=_read_target_file(scenario),
        modified_code=result.fix_code or "",
        top_similarity=top_similarity,
    )

    # 成功した場合は記憶DBに保存
    if result.success and result.fix_code:
        memory_db.save_success(
            error_log=error_log,
            fix_code=result.fix_code,
            scenario=scenario,
            attempts=result.attempts,
        )
    elif not result.success:
        memory_db.save_failure(
            error_log=error_log,
            tried_fixes=[h.get("fix_summary", "") for h in result.history],
            reason=result.stop_reason or "unknown",
            scenario=scenario,
        )

    d = _loop_result_to_dict(result)
    d.update({"confidence_score": cs["score"], "TC": cs["TC"], "SC": cs["SC"], "MS": cs["MS"]})
    return d


# ── ユーティリティ ────────────────────────────

def _get_error_log(scenario: str) -> str:
    """エラーログを実際に取得する（簡易版：シナリオ別の想定エラー文字列）"""
    EXPECTED_ERRORS = {
        "L1-A": "KeyError: 'text' in candidates[0]['content']['parts'][0]",
        "L1-B": "TypeError: can only concatenate str (not 'list') to str",
        "L1-C": "HTTPException: 404 model not found: gemini-pro-deprecated",
        "L2-A": "KeyError: 'task_title' (got 'title')",
        "L2-B": "TypeError: string indices must be integers (user is dict)",
        "L2-C": "TypeError: 'dict' object is not iterable (.map() failed)",
    }
    return EXPECTED_ERRORS.get(scenario, "Unknown error")


def _apply_fix(scenario: str, fix_code: str):
    """修正コードをホワイトリスト内のファイルに適用する"""
    target = ALLOWED_FILES.get(scenario)
    if not target:
        raise PermissionError(f"修正禁止のシナリオ: {scenario}")

    path = Path(target)
    # 適用前バックアップ（実験中のデバッグ容易化）
    path.with_suffix(".py.agent_bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(fix_code, encoding="utf-8")


def _read_target_file(scenario: str) -> str:
    """シナリオに対応するファイルを読み込む"""
    if scenario.startswith("L1"):
        return Path("/app/routers/tasks.py").read_text()
    else:
        return Path("/app/schemas/task.py").read_text()


def _loop_result_to_dict(result) -> dict:
    return {
        "success":     result.success,
        "latency":     result.latency,
        "attempts":    result.attempts,
        "tokens":      result.tokens,
        "stop_reason": result.stop_reason,
    }


# ── メイン実行 ────────────────────────────────

def run_experiments(
    scenarios:  list[str],
    conditions: list[str],
    n_trials:   int,
    output_path: Path,
):
    total = len(scenarios) * len(conditions) * n_trials
    done  = 0
    start_time = datetime.now().strftime("%Y%m%d_%H%M%S")

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp", "scenario", "condition", "trial",
            "success", "latency", "attempts", "tokens", "stop_reason",
            "confidence_score", "TC", "SC", "MS",
        ])
        writer.writeheader()

        for scenario in scenarios:
            for condition in conditions:
                for trial in range(1, n_trials + 1):
                    done += 1
                    print(f"[{done}/{total}] {scenario} × {condition} × trial{trial}")

                    # バグ注入
                    inject(scenario)
                    error_log = _get_error_log(scenario)

                    # 実験実行
                    try:
                        if condition == "bl0":
                            result = run_bl0(scenario, error_log)
                        elif condition == "bl1":
                            result = run_bl1(scenario, error_log)
                        else:
                            result = run_proposed(scenario, error_log, trial)
                    except Exception as e:
                        result = {"success": False, "latency": 0, "attempts": 0,
                                  "tokens": 0, "stop_reason": f"exception:{e}"}

                    # リストア
                    restore()

                    # 結果記録
                    row = {
                        "timestamp": start_time,
                        "scenario":  scenario,
                        "condition": condition,
                        "trial":     trial,
                        "confidence_score": result.get("confidence_score", ""),
                        "TC": result.get("TC", ""), "SC": result.get("SC", ""), "MS": result.get("MS", ""),
                        **{k: result.get(k, "") for k in ["success", "latency", "attempts", "tokens", "stop_reason"]},
                    }
                    writer.writerow(row)
                    f.flush()   # 実験途中でも結果を保存

    print(f"\n実験完了。結果: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario",  default=None, help="特定シナリオのみ実行")
    parser.add_argument("--condition", default=None, help="特定条件のみ実行")
    parser.add_argument("--trials",    type=int, default=N_TRIALS)
    args = parser.parse_args()

    scenarios  = [args.scenario]  if args.scenario  else SCENARIOS
    conditions = [args.condition] if args.condition else CONDITIONS
    output     = RESULTS_DIR / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    RESULTS_DIR.mkdir(exist_ok=True)
    run_experiments(scenarios, conditions, args.trials, output)
