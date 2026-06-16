# -*- coding: utf-8 -*-
"""Warm診断：兄弟シードを記憶に入れた状態でL2-Aを数回回し、
   各試行でエージェントが何を試し、なぜ失敗したかを可視化する。
   「兄弟の具体名(task_name/done)を真似て噛み合っていないか」を確認する。"""
import sys
sys.path.append("/agent"); sys.path.append("/evaluation")
import memory_db, reflection_engine
from inject_bug        import inject, restore
from predefined_tests import run_all_tests
from run_experiments  import _apply_fix, _get_error_log, _read_target_file
from pilot_warm_cold  import SEED_ERROR_LOG, SEED_FIX_CODE, TEST_SCENARIO

N = 3
for t in range(1, N + 1):
    memory_db.reset()
    memory_db.save_success(error_log=SEED_ERROR_LOG, fix_code=SEED_FIX_CODE,
                           scenario="L2-A-seed", attempts=1)
    inject(TEST_SCENARIO)
    try:
        err = _get_error_log(TEST_SCENARIO)
        hits = memory_db.search_similar(err)
        top  = memory_db.get_top_similarity(err)
        res = reflection_engine.run(
            err, hits,
            apply_fix_fn=lambda c: _apply_fix(TEST_SCENARIO, c),
            test_fn=lambda: run_all_tests(TEST_SCENARIO),
            source_code=_read_target_file(TEST_SCENARIO),
        )
        print(f"\n===== warm trial {t} =====")
        print(f"top_similarity={top} / hits={len(hits)} / success={res.success} / attempts={res.attempts}")
        for i, h in enumerate(res.history, 1):
            print(f"  [試行{i}] fix: {h.get('fix_summary','')[:90]!r}")
            print(f"           err: {h.get('error','')[:200]}")
        if res.fix_code:
            print("  --- 最終的に成功した修正(先頭400字) ---")
            print("  " + res.fix_code[:400].replace("\n", "\n  "))
    finally:
        restore()
        memory_db.reset()
