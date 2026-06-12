# -*- coding: utf-8 -*-
"""
Warm / Cold パイロット実験
=====================================================================
目的：
  「関連する過去事例が記憶DBにあると、同種エラーへの復旧に要する
   試行回数(attempts)・レイテンシが減るか」を、独立試行で確認する。

方法論上のポイント（再設計 #1・#3 の反映）：
  - 既存 run_proposed は「trial1だけreset、trial2以降は蓄積」のため、
    記憶効果と trial 番号が交絡し独立性が崩れていた。
  - 本パイロットは【毎試行 reset ＋ ループ後に保存しない】方式に変更。
    reflection_engine.run() は記憶DBに書き込まないので、これだけで
    「測定中はDB状態が固定」＝各試行が i.i.d. になる（凍結フラグ不要）。
  - Cold = 記憶なし(空) / Warm = 同種だが“同一でない”兄弟事例をシード。
  - 主指標は成功率ではなく attempts と latency。

前提：
  - .env で USE_MOCK_GEMINI=false（実LLM）。毎回異なる修正が返り独立性が立つ。
  - 既存ファイルへの改変なし。本ファイルを evaluation/ に置いて実行するだけ。

実行：
  docker-compose run agent python /evaluation/pilot_warm_cold.py
出力：
  /results/pilot_warm_cold.csv ＋ コンソールのサマリ
"""
import csv
import statistics
import sys

sys.path.append("/agent")
sys.path.append("/evaluation")

import memory_db
import reflection_engine
from inject_bug        import inject, restore
from predefined_tests import run_all_tests
from confidence_score import compute_all
from run_experiments  import _apply_fix, _read_target_file, _get_error_log

# ------------------------------------------------------------------ 設定
TEST_SCENARIO = "L1-A"     # 既存シナリオを流用（注入・テストはそのまま）
N_TRIALS      = 20         # 各条件20試行（パイロットは傾向確認で十分）
OUT           = "/results/pilot_warm_cold.csv"

# Warm 用シード：L1-A と「同種だが同一でない」兄弟事例。
#  - error_log: L1-A の想定エラー（"KeyError: 'text' ..."）と構造は同じだがキーが違う
#  - fix_code : 過去の兄弟修正（防御的パースの型）。テストの正解そのものではない
SEED_ERROR_LOG = (
    "KeyError: 'result' in candidates[0]['content']['parts'][0] "
    "（Gemini応答スキーマ変更で期待キーが見つからない）"
)
SEED_FIX_CODE = (
    "# 過去の兄弟ケースの修正例：応答パースを防御的に行いキー名の揺れを吸収する\n"
    "parts = data['candidates'][0]['content']['parts'][0]\n"
    "text = parts.get('result', parts.get('output', parts.get('text', '')))\n"
    "if isinstance(text, list):\n"
    "    text = text[0]\n"
    "summary = str(text)\n"
)

# ------------------------------------------------------------------ 1試行
def one_trial(condition: str) -> dict:
    # 毎試行 DB を初期化 → 独立性の確保
    memory_db.reset()
    if condition == "warm":
        memory_db.save_success(
            error_log=SEED_ERROR_LOG,
            fix_code=SEED_FIX_CODE,
            scenario="L1-A-seed",       # テスト対象とは別IDで“同一でない”ことを明示
            attempts=1,
        )

    inject(TEST_SCENARIO)
    error_log = _get_error_log(TEST_SCENARIO)

    # Cold は記憶を渡さない。Warm は類似検索（閾値0.75以上のみ返る）
    memory_hits = memory_db.search_similar(error_log) if condition == "warm" else []
    top_sim     = memory_db.get_top_similarity(error_log) if condition == "warm" else None

    result = reflection_engine.run(
        error_log=error_log,
        memory_hits=memory_hits,
        apply_fix_fn=lambda code: _apply_fix(TEST_SCENARIO, code),
        test_fn=lambda: run_all_tests(TEST_SCENARIO),
    )

    # 信頼スコア（SCが機能しているかの確認用）。修正適用中＝restore前に算出する
    cs = {"score": None, "TC": None, "SC": None, "MS": None}
    if result.success and result.fix_code:
        try:
            tr = run_all_tests(TEST_SCENARIO)
            cs = compute_all(
                test_results=tr.get("details", []),
                original_code=_read_target_file(TEST_SCENARIO),
                modified_code=result.fix_code,
                top_similarity=top_sim,
            )
        except Exception as e:
            print("  (信頼スコア算出スキップ)", e)

    restore()
    memory_db.reset()   # 後片付け（蓄積を残さない＝独立性の担保）

    return {
        "condition":   condition,
        "success":     int(bool(result.success)),
        "attempts":    result.attempts,
        "latency_s":   result.latency,
        "tokens":      result.tokens,
        "stop_reason": result.stop_reason,
        "n_hits":      len(memory_hits),
        "MS":          cs.get("MS"),
        "SC":          cs.get("SC"),
        "TC":          cs.get("TC"),
    }

# ------------------------------------------------------------------ 集計
def summarize(rows):
    print("\n==== サマリ（成功試行のみ）====")
    for cond in ["cold", "warm"]:
        a  = [r["attempts"]  for r in rows if r["condition"] == cond and r["success"]]
        l  = [r["latency_s"] for r in rows if r["condition"] == cond and r["success"]]
        sc = [r["SC"] for r in rows if r["condition"] == cond and r["SC"] is not None]
        hit = [r["n_hits"] for r in rows if r["condition"] == cond]
        succ = sum(r["success"] for r in rows if r["condition"] == cond)
        n    = sum(1 for r in rows if r["condition"] == cond)
        ma = statistics.median(a) if a else "NA"
        ml = statistics.median(l) if l else "NA"
        scr = (round(min(sc), 2), round(max(sc), 2)) if sc else "NA"
        hm = statistics.mean(hit) if hit else 0
        print(f"[{cond}] 成功 {succ}/{n} / attempts中央値={ma} / latency中央値={ml}s "
              f"/ 平均ヒット数={hm:.1f} / SCレンジ={scr}")
    try:
        from scipy.stats import mannwhitneyu
        ca = [r["attempts"] for r in rows if r["condition"] == "cold" and r["success"]]
        wa = [r["attempts"] for r in rows if r["condition"] == "warm" and r["success"]]
        if ca and wa:
            _, p = mannwhitneyu(wa, ca, alternative="less")
            print(f"Wilcoxon（warm attempts < cold）片側 p = {p:.4f}")
    except Exception as e:
        print("（検定スキップ）", e)

    print("\n---- Go/No-Go の目安 ----")
    print("✓ Warm の attempts 中央値 < Cold（傾向でOK, p<0.1 なら好材料）")
    print("✓ Warm の平均ヒット数 > 0（シードが類似0.75以上で拾われている。0なら SEED_ERROR_LOG を寄せる）")
    print("✓ attempts が 1 に張り付かず分散（変種が適度に難しい）")
    print("✓ SC が全て 0 でない（0なら whole-file 出力 → Phase2 で diff 化）")

# ------------------------------------------------------------------ main
def main():
    fields = ["condition", "success", "attempts", "latency_s", "tokens",
              "stop_reason", "n_hits", "MS", "SC", "TC"]
    rows = []
    # 1試行ごとに書き出し＆flush → 途中で中断/クラッシュしても結果が残る
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); f.flush()
        for cond in ["cold", "warm"]:
            for i in range(N_TRIALS):
                r = one_trial(cond)
                rows.append(r)
                w.writerow(r); f.flush()
                print(f"{cond} {i+1}/{N_TRIALS}: success={r['success']} "
                      f"attempts={r['attempts']} hits={r['n_hits']}")
    print("\nsaved:", OUT)
    summarize(rows)

if __name__ == "__main__":
    main()
