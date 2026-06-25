# -*- coding: utf-8 -*-
"""
Warm シード定義（兄弟＝同種だが同一でない成功事例）。
run_bugsinpy_memory.py が SEED_KEY="proj:bug" で引く。

構成方針（artifact 回避）：
  人手で“正解技法”を書くとリークになりうる。可能なら **同種の別バグ（donor bug）の
  実際の修正**を fix_code に使う：
    1) donor バグを fixed(v1) で checkout し、buggy(v0) との diff を取得。
    2) その失敗テスト出力を error_log に、diff（または修正後の該当箇所）を fix_code に。
  これで「過去に実際に直した兄弟ケース」を記憶として与える＝現実的で公正。

各エントリ:
  "proj:bug": {
      "error_log": "<donor の失敗テスト要約 or 例外メッセージ>",
      "fix_code":  "<donor の効いた修正（diff/該当箇所）>",
  }
"""

SEEDS = {
    # 例（要差し替え）：black の donor バグから作る。
    # "black:<target_bug>": {
    #     "error_log": "AssertionError: ... (black:<donor_bug> の失敗テスト)",
    #     "fix_code":  "--- a/src/black/...\n+++ b/src/black/...\n@@ ...\n- <旧>\n+ <新>\n",
    # },
}
