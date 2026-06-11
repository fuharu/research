# research-self-evolving-agent

実行時エラーの自己内省に基づくLLMエージェントの動的コード修正・自己進化アーキテクチャの提案と評価

## セットアップ

```bash
cp .env.example .env
# GEMINI_API_KEY を設定する

docker-compose up --build
```

## 実験の実行

```bash
# 360実験を全自動実行
docker-compose run agent python /evaluation/run_experiments.py

# 特定シナリオのみ（動作確認用）
docker-compose run agent python /evaluation/run_experiments.py --scenario L1-A --condition proposed --trials 3
```

## ディレクトリ構成

```
app/                  FastAPI本体（修正可能な層）
  routers/tasks.py    ★ L1系バグ注入対象
  schemas/task.py     ★ L2系バグ注入対象
frontend/             React本体
agent/
  reflection_engine.py  リフレクションエンジン
  memory_db.py          Chroma記憶DB（EMBEDDING_VERSIONで固定）
  confidence_score.py   信頼スコア算出（TC×0.5 + SC×0.3 + MS×0.2）
evaluation/
  inject_bug.py         バグ注入スクリプト（6シナリオ）
  mock_gemini_server.py Gemini APIモック
  predefined_tests.py   事前定義テストセット（自己循環問題対策）
  run_experiments.py    360実験の自動実行
results/              実験結果CSV（.gitignore に追加しない）
```

## 実験設計

| 項目 | 値 |
|------|-----|
| シナリオ数 | 6（L1-A/B/C・L2-A/B/C） |
| 条件数 | 3（BL0・BL1・提案手法） |
| 試行回数 | 20回/条件/シナリオ |
| 総実験数 | 360回 |
| 主指標 | 復旧成功率（Fisher正確検定）|
| 副指標 | 復旧レイテンシ（Wilcoxon順位和検定）|
| 多重比較補正 | Bonferroni（α=0.0042）|

## 埋め込みモデルのバージョン固定

実験の再現性確保のため、`.env` の `EMBEDDING_MODEL` と `EMBEDDING_VERSION` は
実験期間中に変更しないこと。
記憶DBのコレクション名にバージョンを含めることで、モデル更新時の混在を防いでいる。
