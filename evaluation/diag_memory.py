# -*- coding: utf-8 -*-
"""記憶検索の生診断：コレクションの距離方式と、シードvsL1-Aの実類似度を出す。"""
import sys
sys.path.append("/agent"); sys.path.append("/evaluation")
import memory_db
from run_experiments import _get_error_log
from pilot_warm_cold import SEED_ERROR_LOG   # パイロットと同一のシード文を使う

col = memory_db._get_collection()
print("provider          :", memory_db.EMBEDDING_PROVIDER)
print("collection name   :", col.name)
print("collection metadata:", col.metadata, "  ← {'hnsw:space':'cosine'} になっているか")
print("threshold         :", memory_db.SIMILARITY_THRESHOLD)

memory_db.reset()
memory_db.save_success(error_log=SEED_ERROR_LOG, fix_code="dummy", scenario="seed", attempts=1)

err = _get_error_log("L1-A")
print("\nSEED :", SEED_ERROR_LOG)
print("QUERY:", err)

res = col.query(query_texts=[err], n_results=1, include=["documents", "distances"])
dist = res["distances"][0][0]
print("\nraw distance      :", round(dist, 4))
print("similarity(1-dist):", round(1.0 - dist, 4), "  ← 0.75以上ならhitする")
print("search_similar hits:", len(memory_db.search_similar(err)))
memory_db.reset()
