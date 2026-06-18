# -*- coding: utf-8 -*-
"""
QuixBugs で ②エージェントループの配線derisk（Coldのみ）。
1プログラム=単一ファイル。pytestの失敗を error_log として渡し、
エージェントが read_file → apply_fix で直し、pytestが通るか確認する。
前提: リポジトリ直下に QuixBugs を clone（/evaluation/QuixBugs）。
実行: docker compose run --rm agent python /evaluation/run_quixbugs_agentic.py
"""
import subprocess, sys
from pathlib import Path
sys.path.append("/agent"); sys.path.append("/evaluation")
import agentic_loop

QUIX = "/evaluation/QuixBugs"
# タイムアウト不要・高速な代表プログラムを少数
PROGRAMS = ["gcd", "sieve", "lis", "flatten", "quicksort",
            "bucketsort", "get_factors", "to_base"]

def make_test(name):
    def _t():
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--timeout=15",
             f"python_testcases/test_{name}.py"],
            cwd=QUIX, capture_output=True, text=True)
        ok = (r.returncode == 0)
        return {"all_passed": ok,
                "details": [{"name": f"pytest_{name}", "passed": ok}],
                "out": (r.stdout + r.stderr)[-1500:]}
    return _t

def main():
    if not Path(QUIX).exists():
        print(f"!! {QUIX} が見つかりません。先に clone してください。"); return
    rows = []
    for name in PROGRAMS:
        f = f"{QUIX}/python_programs/{name}.py"
        if not Path(f).exists():
            print(f"  skip {name}（ファイルなし）"); continue
        buggy = Path(f).read_text(encoding="utf-8")
        tf = make_test(name)
        pre = tf()
        if pre["all_passed"]:
            print(f"  skip {name}（バグ版が最初から通る）"); continue
        err = f"pytest が失敗しています（{name}）:\n{pre.get('out','')[-800:]}"
        try:
            res = agentic_loop.run(
                err, [], readable={f}, writable={f},
                read_file_fn=lambda p: Path(p).read_text(encoding="utf-8"),
                apply_fix_fn=lambda p, c: Path(p).write_text(c, encoding="utf-8"),
                test_fn=tf)
            print(f"{name}: success={int(res.success)} iters={res.iters} "
                  f"reads={res.reads} attempts={res.attempts} stop={res.stop_reason}")
            rows.append((name, res.success))
        finally:
            Path(f).write_text(buggy, encoding="utf-8")   # 後片付け（バグ版へ復元）
    ok = sum(1 for _, s in rows if s)
    print(f"\n==== QuixBugs derisk: {ok}/{len(rows)} solved ====")
    print("（配線確認が目的。解ければベンチ→②の接続OK。次はBugsInPyで記憶実験）")

if __name__ == "__main__":
    main()
