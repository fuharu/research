# -*- coding: utf-8 -*-
"""失敗シナリオ診断：なぜ常に5回失敗するのか（どのテストが落ちているか）を可視化。"""
import os, sys, json
sys.path.append("/agent"); sys.path.append("/evaluation")
import reflection_engine
from inject_bug        import inject, restore
from predefined_tests import run_all_tests
from run_experiments  import _apply_fix, _get_error_log

SCN = os.getenv("DIAG_SCENARIO", "L2-A")
inject(SCN)
try:
    err = _get_error_log(SCN)
    print("=== scenario:", SCN, "===")
    print("ERROR LOG:", err)
    res = reflection_engine.run(
        err, [],
        apply_fix_fn=lambda c: _apply_fix(SCN, c),
        test_fn=lambda: run_all_tests(SCN),
    )
    print("\nsuccess =", res.success, "/ attempts =", res.attempts, "/ stop =", res.stop_reason)
    print("\n=== 各試行の要約と失敗理由（history）===")
    for i, h in enumerate(res.history, 1):
        print(f"[{i}] fix: {h.get('fix_summary','')[:80]!r}")
        print(f"    err: {h.get('error','')[:300]}")
    print("\n=== 最後に適用された状態でのテスト詳細 ===")
    tr = run_all_tests(SCN)
    print(json.dumps(tr, ensure_ascii=False, indent=2)[:3000])
finally:
    restore()
