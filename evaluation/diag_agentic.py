# -*- coding: utf-8 -*-
"""②ループの挙動を1試行ずつ詳細表示（cold/warm 各1）。read/apply の流れと失敗理由を見る。"""
import sys
sys.path.append("/agent"); sys.path.append("/evaluation")
import memory_db, agentic_loop
from inject_bug        import inject, restore
from predefined_tests import run_all_tests
from run_experiments  import _get_error_log
from pilot_warm_cold  import SEED_ERROR_LOG, SEED_FIX_CODE
from pathlib import Path

SCN="L2-A"
READABLE={"/app/main.py","/app/routers/tasks.py","/app/schemas/task.py"}
WRITABLE={"/app/routers/tasks.py","/app/schemas/task.py"}

def trial(condition):
    memory_db.reset()
    if condition=="warm":
        memory_db.save_success(error_log=SEED_ERROR_LOG,fix_code=SEED_FIX_CODE,scenario="L2-A-seed",attempts=1)
    inject(SCN)
    buggy={p:Path(p).read_text(encoding="utf-8") for p in WRITABLE}
    def revert():
        for p,c in buggy.items(): Path(p).write_text(c,encoding="utf-8")
    try:
        err=_get_error_log(SCN)
        hits=memory_db.search_similar(err) if condition=="warm" else []
        res=agentic_loop.run(err,hits,READABLE,WRITABLE,
            read_file_fn=lambda p:Path(p).read_text(encoding="utf-8"),
            apply_fix_fn=lambda p,c:Path(p).write_text(c,encoding="utf-8"),
            test_fn=lambda:run_all_tests(SCN), revert_fn=revert)
        print(f"\n========== {condition} : success={res.success} iters={res.iters} reads={res.reads} attempts={res.attempts} stop={res.stop_reason} hits={len(hits)} ==========")
        for i,h in enumerate(res.history,1):
            print(f"[{i}] {h.get('act','')}  ->  {h.get('obs','')[:140]}")
            if h.get("code"): print(f"      code先頭: {h['code'][:140]!r}")
    finally:
        restore(); memory_db.reset()

trial("cold")
trial("warm")
