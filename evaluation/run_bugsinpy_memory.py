# -*- coding: utf-8 -*-
"""
本実験：②（能動的情報収集）× BugsInPy で「ハーネス情報供給度×記憶」の効率を測る。
=====================================================================
設計（pilot_warm_cold.py の BugsInPy 版）：
  - Cold = 記憶なし / Warm = 対象バグの“兄弟”（同種だが同一でない）成功事例をシード。
  - ②ループは read_file/search_in_file/read_lines で原因を特定し edit_file で直す。
    候補ファイル＝bench_retrieval の top-K（リポジトリ構成は既知＝ギャップではない）。
  - 毎試行：memory_db.reset → (warmならseed) → 候補をバグ状態に復元 → ②実行 → 復元。
  - 主指標：attempts / iters / reads / latency / tokens / success。
  - 検定：Wilcoxon（warm < cold）を attempts と iters に。
  - DEBUG=1 で各試行の行動ログを出力（探索の挙動確認用）。

実行：
  docker compose run --rm -e PROJ=black -e BUG=<id> -e SEED_KEY=black:<donor> \
      -e N_TRIALS=15 agent python /evaluation/run_bugsinpy_memory.py
出力：
  /results/bugsinpy_memory_<proj>_<bug>.csv ＋ コンソールのサマリ
"""
import csv
import os
import statistics
import sys
from pathlib import Path

sys.path.append("/agent")
sys.path.append("/evaluation")

import agentic_loop
import memory_db
import bench_bugsinpy as B
import bench_retrieval as R

try:
    import bugsinpy_seeds
except Exception:
    bugsinpy_seeds = None

PROJ        = os.getenv("PROJ", "black")
BUG         = os.getenv("BUG", "")
N_TRIALS    = int(os.getenv("N_TRIALS", "15"))
TOPK        = int(os.getenv("TOPK", "12"))
REVERT_ON_FAIL = os.getenv("REVERT_ON_FAIL", "1") == "1"
SEED_KEY    = os.getenv("SEED_KEY", f"{PROJ}:{BUG}")
OUT         = os.getenv("OUT", f"/results/bugsinpy_memory_{PROJ}_{BUG or 'x'}.csv")
DEBUG       = os.getenv("DEBUG") == "1"


def _load_seed():
    el = os.getenv("SEED_ERROR_LOG")
    fc = os.getenv("SEED_FIX_CODE")
    if el and fc:
        return {"error_log": el, "fix_code": fc}
    if bugsinpy_seeds and hasattr(bugsinpy_seeds, "SEEDS"):
        s = bugsinpy_seeds.SEEDS.get(SEED_KEY)
        if s:
            return s
    return None


def main():
    pdir = B.project_dir(PROJ)
    if not Path(pdir).exists():
        print(f"!! {pdir} が無い。bugsinpyコンテナで {PROJ} の対象バグを checkout 済みか確認。")
        return

    pre = B.run_bugsinpy_test(PROJ)
    print("buggy test all_passed:", pre["all_passed"], "（False=バグ再現中＝正常）")
    if pre["all_passed"]:
        print("!! buggy で既に PASS。対象バグが checkout されていない可能性。中止。")
        return
    error_log = f"テストが失敗しています（{PROJ}）:\n{pre['out'][-1200:]}"

    cands = R.retrieve(pdir, pre["out"], k=TOPK)
    cand_paths = {fp for fp, _ in cands}
    print(f"top-{TOPK} candidate files:")
    for fp, nl in cands:
        print(f"  {nl:5}行  {fp.replace(pdir+'/','')}")

    backup = {fp: Path(fp).read_text(encoding="utf-8", errors="replace") for fp in cand_paths}
    def revert_all():
        for fp, txt in backup.items():
            Path(fp).write_text(txt, encoding="utf-8")

    seed = _load_seed()
    print(f"\nSEED_KEY={SEED_KEY} / seed {'あり' if seed else 'なし（warm不可→coldのみ意味あり）'}")

    fields = ["condition", "proj", "bug", "success", "attempts", "iters",
              "reads", "latency_s", "tokens", "n_hits", "stop_reason"]
    rows = []

    def one_trial(condition: str) -> dict:
        memory_db.reset()
        if condition == "warm" and seed:
            memory_db.save_success(
                error_log=seed["error_log"], fix_code=seed["fix_code"],
                scenario=f"{SEED_KEY}-seed", attempts=1,
            )
        revert_all()

        memory_hits = memory_db.search_similar(error_log) if condition == "warm" else []
        res = None
        try:
            res = agentic_loop.run(
                error_log, memory_hits,
                readable=cand_paths, writable=cand_paths,
                read_file_fn=lambda p: Path(p).read_text(encoding="utf-8", errors="replace"),
                apply_fix_fn=lambda p, c: Path(p).write_text(c, encoding="utf-8"),
                test_fn=lambda: B.run_bugsinpy_test(PROJ),
                revert_fn=(revert_all if REVERT_ON_FAIL else None),
            )
        finally:
            revert_all()
            memory_db.reset()
        if DEBUG and res is not None:
            print(f"  --- {condition} 行動ログ（iters={res.iters} reads={res.reads} "
                  f"attempts={res.attempts} stop={res.stop_reason}）---")
            for a in res.history:
                print("    ·", a)
        return {
            "condition": condition, "proj": PROJ, "bug": BUG,
            "success": int(bool(res.success)) if res else 0,
            "attempts": res.attempts if res else 0,
            "iters": res.iters if res else 0,
            "reads": res.reads if res else 0,
            "latency_s": res.latency if res else 0,
            "tokens": res.tokens if res else 0,
            "n_hits": len(memory_hits),
            "stop_reason": res.stop_reason if res else "error",
        }

    conditions = ["cold", "warm"] if seed else ["cold"]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); f.flush()
        for cond in conditions:
            for i in range(N_TRIALS):
                r = one_trial(cond)
                rows.append(r); w.writerow(r); f.flush()
                print(f"{cond} {i+1}/{N_TRIALS}: success={r['success']} "
                      f"attempts={r['attempts']} iters={r['iters']} reads={r['reads']} "
                      f"hits={r['n_hits']} stop={r['stop_reason']}")
    print("\nsaved:", OUT)
    summarize(rows)


def summarize(rows):
    print("\n==== サマリ（成功試行のみ）====")
    for cond in ["cold", "warm"]:
        rs = [r for r in rows if r["condition"] == cond]
        if not rs:
            continue
        succ = sum(r["success"] for r in rs)
        a = [r["attempts"] for r in rs if r["success"]]
        it = [r["iters"]   for r in rs if r["success"]]
        l = [r["latency_s"] for r in rs if r["success"]]
        hit = statistics.mean([r["n_hits"] for r in rs]) if rs else 0
        ma = statistics.median(a) if a else "NA"
        mi = statistics.median(it) if it else "NA"
        ml = statistics.median(l) if l else "NA"
        print(f"[{cond}] 成功 {succ}/{len(rs)} / attempts中央値={ma} / iters中央値={mi} "
              f"/ latency中央値={ml}s / 平均ヒット={hit:.1f}")
    try:
        from scipy.stats import mannwhitneyu
        for key in ("attempts", "iters"):
            ca = [r[key] for r in rows if r["condition"] == "cold" and r["success"]]
            wa = [r[key] for r in rows if r["condition"] == "warm" and r["success"]]
            if ca and wa:
                _, p = mannwhitneyu(wa, ca, alternative="less")
                print(f"Wilcoxon（warm {key} < cold）片側 p = {p:.4f}")
    except Exception as e:
        print("（検定スキップ）", e)


if __name__ == "__main__":
    main()
