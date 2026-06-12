# -*- coding: utf-8 -*-
"""閾値較正：シードと各シナリオエラーのコサイン類似度を実測し、
   「同種(L1系)は高く／別種(L2系)は低く」分離できる閾値を探す。
   現行シード(日本語注釈付き)と、注釈を削った清書シードの両方で比較する。"""
import sys
sys.path.append("/agent"); sys.path.append("/evaluation")
import memory_db
from run_experiments import _get_error_log
from pilot_warm_cold import SEED_ERROR_LOG

SCENARIOS = ["L1-A", "L1-B", "L1-C", "L2-A", "L2-B", "L2-C"]
seeds = {
    "current(注釈あり)": SEED_ERROR_LOG,
    "cleaned(注釈なし)": "KeyError: 'result' in candidates[0]['content']['parts'][0]",
}

col = memory_db._get_collection()
print("collection:", col.name, col.metadata)

# 参考：各シナリオのエラー文を一覧
print("\n=== 各シナリオの error_log ===")
for scn in SCENARIOS:
    print(f"  {scn:5}: {_get_error_log(scn)}")

for sname, stext in seeds.items():
    memory_db.reset()
    memory_db.save_success(error_log=stext, fix_code="x", scenario="seed", attempts=1)
    print(f"\n=== seed = {sname} ===")
    print("  seed text:", stext)
    rows = []
    for scn in SCENARIOS:
        err = _get_error_log(scn)
        r = col.query(query_texts=[err], n_results=1, include=["distances"])
        rows.append((1.0 - r["distances"][0][0], scn))
    for sim, scn in sorted(rows, reverse=True):
        fam = "同種(L1系)" if scn.startswith("L1") else "別種(L2系)"
        print(f"  sim={sim:.3f}  {scn:5} [{fam}]")
    memory_db.reset()

print("\n---- 見方 ----")
print("・L1系(同種)が高く、L2系(別種)が低く分かれていれば、その谷に閾値を置けばよい")
print("・分離しない(全部似た値)なら、エラー文が短すぎる→ログにcontext(関数名/該当行)を足す検討")
