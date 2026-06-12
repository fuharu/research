# -*- coding: utf-8 -*-
"""
シナリオ難易度スキャン（Cold のみ）
=====================================================================
目的：
  Warm/Cold 比較で「記憶が試行回数を減らす」効果を見るには、
  Cold が時々 1 回で解けない＝適度に難しいシナリオが必要。
  L1-A は Claude Haiku 4.5 にとって簡単すぎ（attempts が 1 に張り付く）。
  そこで 6 シナリオ全てを Cold（記憶なし）で数回ずつ回し、
  「成功率」と「attempts の分布」から本実験向きの難シナリオを選ぶ。

方法：
  各シナリオを K 回、記憶なし(memory_hits=[]) で reflection ループにかける。
  毎試行 inject → run → restore でベースラインを汚さない。

実行：
  docker compose run --rm agent python /evaluation/scenario_difficulty_scan.py
出力：
  /results/scenario_difficulty_scan.csv ＋ コンソールのサマリ
"""
import csv
import statistics
import sys
import traceback

sys.path.append("/agent")
sys.path.append("/evaluation")

import reflection_engine
from inject_bug        import inject, restore
from predefined_tests import run_all_tests
from run_experiments  import _apply_fix, _get_error_log

# ------------------------------------------------------------------ 設定
SCENARIOS = ["L1-A", "L1-B", "L1-C", "L2-A", "L2-B", "L2-C"]
K         = 5          # 各シナリオ K 回（傾向確認用。難易度の当たりを付けるだけ）
OUT       = "/results/scenario_difficulty_scan.csv"

# ------------------------------------------------------------------ 1試行
def one_cold_trial(scenario: str) -> dict:
    inject(scenario)
    try:
        error_log = _get_error_log(scenario)
        result = reflection_engine.run(
            error_log=error_log,
            memory_hits=[],                       # Cold = 記憶なし
            apply_fix_fn=lambda code: _apply_fix(scenario, code),
            test_fn=lambda: run_all_tests(scenario),
        )
        return {
            "scenario":    scenario,
            "success":     int(bool(result.success)),
            "attempts":    result.attempts,
            "latency_s":   result.latency,
            "stop_reason": result.stop_reason,
        }
    finally:
        restore()   # 適用した修正を必ず戻す（次試行のベースライン汚染防止）

# ------------------------------------------------------------------ main
def main():
    fields = ["scenario", "success", "attempts", "latency_s", "stop_reason"]
    rows = []
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); f.flush()
        for sc in SCENARIOS:
            for i in range(K):
                try:
                    r = one_cold_trial(sc)
                except Exception as e:
                    # シナリオ未実装などはスキップして続行
                    print(f"  [{sc}] 試行{i+1} 例外: {e}")
                    traceback.print_exc()
                    r = {"scenario": sc, "success": 0, "attempts": -1,
                         "latency_s": 0, "stop_reason": "exception"}
                rows.append(r)
                w.writerow(r); f.flush()
                print(f"{sc} {i+1}/{K}: success={r['success']} "
                      f"attempts={r['attempts']} stop={r['stop_reason']}")

    print("\n==== シナリオ別サマリ ====")
    print(f"{'scenario':8} {'成功率':>8} {'attempts中央値':>14}  attempts分布")
    for sc in SCENARIOS:
        rs = [r for r in rows if r["scenario"] == sc]
        if not rs:
            continue
        succ = sum(r["success"] for r in rs)
        a_ok = [r["attempts"] for r in rs if r["success"]]
        med  = statistics.median(a_ok) if a_ok else "NA"
        dist = sorted(r["attempts"] for r in rs)
        print(f"{sc:8} {succ:>3}/{len(rs):<4} {str(med):>14}  {dist}")

    print("\n---- 選定の目安 ----")
    print("・本実験向き = 成功率がほどほど(例 5〜9割)で attempts が 1 に張り付かず分散するシナリオ")
    print("・全部 attempts=1 なら簡単すぎ／全部失敗なら難しすぎ（バグor前提を見直す）")
    print("saved:", OUT)

if __name__ == "__main__":
    main()
