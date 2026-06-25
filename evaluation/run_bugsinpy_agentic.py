# -*- coding: utf-8 -*-
"""
②×BugsInPy retrieval-derisk（Coldのみ）。
失敗テスト→retrievalで候補top-K→②ループが read_file/apply_fix→bugsinpy-test。
※現状は「ファイル全体書換」方式のため、対象ファイルが小さいバグで使うこと
　（巨大ファイルはツール探索フェーズでpatch化）。
前提: bugsinpy コンテナ起動中＆対象バグが buggy(v0) で checkout 済み。
実行: docker compose run --rm -e PROJ=<proj> agent python /evaluation/run_bugsinpy_agentic.py
"""
import os, sys
from pathlib import Path
sys.path.append("/agent"); sys.path.append("/evaluation")
import agentic_loop
import bench_bugsinpy as B
import bench_retrieval as R

PROJ = os.getenv("PROJ", "youtube-dl")
K    = int(os.getenv("TOPK", "12"))

def main():
    pdir = B.project_dir(PROJ)
    if not Path(pdir).exists():
        print(f"!! {pdir} が無い。bugsinpyコンテナで対象バグを checkout 済みか確認。"); return

    pre = B.run_bugsinpy_test(PROJ)
    print("buggy test all_passed:", pre["all_passed"], "（Falseが正常＝バグ再現中）")
    query = pre["out"]

    cands = R.retrieve(pdir, query, k=K)
    print(f"\ntop-{K} candidates（行数）:")
    for fp, nl in cands:
        print(f"  {nl:5}行  {fp.replace(pdir+'/','')}")
    big = [fp for fp, nl in cands if nl > 400]
    if big:
        print(f"\n注意: 400行超の候補が {len(big)} 件。全体書換方式では直しにくい→小ファイルのバグ推奨。")

    if os.getenv("RETRIEVE_ONLY") == "1":
        print("\n(RETRIEVE_ONLY: retrieval確認のみで終了)"); return

    cand_paths = {fp for fp, nl in cands}
    backup = {fp: Path(fp).read_text(encoding="utf-8", errors="replace") for fp in cand_paths}
    def revert():
        for fp, txt in backup.items():
            Path(fp).write_text(txt, encoding="utf-8")

    err = f"テストが失敗しています（{PROJ}）:\n{query[-1000:]}"
    try:
        res = agentic_loop.run(
            err, [], readable=cand_paths, writable=cand_paths,
            read_file_fn=lambda p: Path(p).read_text(encoding="utf-8", errors="replace"),
            apply_fix_fn=lambda p, c: Path(p).write_text(c, encoding="utf-8"),
            test_fn=lambda: B.run_bugsinpy_test(PROJ))
            # 注: BugsInPyはサーバ無し＆複数ファイル修正があるため、試行内は復元しない
            #     （編集を累積させる）。試行間のリセットは finally の revert() で行う。
        print(f"\nRESULT: success={res.success} iters={res.iters} reads={res.reads} "
              f"attempts={res.attempts} stop={res.stop_reason}")
        print("（success=Trueなら retrieval→②→test の本接続OK）")
    finally:
        revert()

if __name__ == "__main__":
    main()
