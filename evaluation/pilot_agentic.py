# -*- coding: utf-8 -*-
"""
②能動的情報収集（agentic）での Warm/Cold パイロット
=====================================================================
①と違い、ソースは渡さない。エージェントが read_file で原因ファイルを
自分で特定し、apply_fix で直す。記憶（兄弟事例）が localization と
手法選択を助け、reads / iters / attempts を減らすかを測る。
実行: docker compose run --rm agent python /evaluation/pilot_agentic.py
"""
import csv, statistics, sys
sys.path.append("/agent"); sys.path.append("/evaluation")

import memory_db
import agentic_loop
from inject_bug        import inject, restore
from predefined_tests import run_all_tests
from run_experiments  import _get_error_log
from pilot_warm_cold  import SEED_ERROR_LOG, SEED_FIX_CODE   # 兄弟シードを共有

from pathlib import Path

TEST_SCENARIO = "L2-A"
N_TRIALS      = 15
OUT           = "/results/pilot_agentic.csv"

READABLE = {"/app/main.py", "/app/routers/tasks.py", "/app/schemas/task.py"}
WRITABLE = {"/app/routers/tasks.py", "/app/schemas/task.py"}

def _read_file(path):  return Path(path).read_text(encoding="utf-8")
def _apply_fix(path, code): Path(path).write_text(code, encoding="utf-8")

def one_trial(condition):
    memory_db.reset()
    if condition == "warm":
        memory_db.save_success(error_log=SEED_ERROR_LOG, fix_code=SEED_FIX_CODE,
                               scenario="L2-A-seed", attempts=1)
    inject(TEST_SCENARIO)
    try:
        error_log = _get_error_log(TEST_SCENARIO)
        hits = memory_db.search_similar(error_log) if condition == "warm" else []
        res = agentic_loop.run(
            error_log=error_log, memory_hits=hits,
            readable=READABLE, writable=WRITABLE,
            read_file_fn=_read_file, apply_fix_fn=_apply_fix,
            test_fn=lambda: run_all_tests(TEST_SCENARIO),
        )
        return {"condition":condition, "success":int(bool(res.success)),
                "attempts":res.attempts, "iters":res.iters, "reads":res.reads,
                "latency_s":res.latency, "tokens":res.tokens,
                "n_hits":len(hits), "stop_reason":res.stop_reason}
    finally:
        restore(); memory_db.reset()

def summarize(rows):
    print("\n==== サマリ ====")
    for cond in ["cold","warm"]:
        rs=[r for r in rows if r["condition"]==cond]
        succ=sum(r["success"] for r in rs); n=len(rs)
        ok=[r for r in rs if r["success"]]
        def med(k): 
            v=[r[k] for r in ok]; return statistics.median(v) if v else "NA"
        hm=statistics.mean([r["n_hits"] for r in rs]) if rs else 0
        print(f"[{cond}] 成功 {succ}/{n} / iters中央値={med('iters')} / reads中央値={med('reads')} "
              f"/ attempts中央値={med('attempts')} / latency中央値={med('latency_s')}s / 平均ヒット={hm:.1f}")
    try:
        from scipy.stats import mannwhitneyu
        for k in ["iters","reads","attempts"]:
            c=[r[k] for r in rows if r["condition"]=="cold" and r["success"]]
            w=[r[k] for r in rows if r["condition"]=="warm" and r["success"]]
            if c and w:
                _,p=mannwhitneyu(w,c,alternative="less")
                print(f"Wilcoxon（warm {k} < cold）片側 p = {p:.4f}")
    except Exception as e:
        print("（検定スキップ）", e)
    print("\n---- Go/No-Go ----")
    print("✓ Warm の reads/iters 中央値 < Cold（記憶が localization を助ける）")
    print("✓ Warm の平均ヒット > 0（兄弟事例が拾われている）")

def main():
    fields=["condition","success","attempts","iters","reads","latency_s","tokens","n_hits","stop_reason"]
    rows=[]
    with open(OUT,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); f.flush()
        for cond in ["cold","warm"]:
            for i in range(N_TRIALS):
                r=one_trial(cond); rows.append(r); w.writerow(r); f.flush()
                print(f"{cond} {i+1}/{N_TRIALS}: success={r['success']} iters={r['iters']} "
                      f"reads={r['reads']} attempts={r['attempts']} hits={r['n_hits']} stop={r['stop_reason']}")
    print("\nsaved:", OUT); summarize(rows)

if __name__ == "__main__":
    main()
