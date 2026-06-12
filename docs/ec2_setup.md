# EC2 セットアップ手順（自己進化エージェント実験を AWS 上で回す）

ローカルPCではなく EC2 上で docker-compose をそのまま動かし、**Bedrock を IAMロールで利用（キー不要）**、長時間の実験を**放置で安定実行**するための手順。

> 前提：これは「Webアプリの公開デプロイ」ではなく「計算ホストを1台借りて、今のリポジトリをそのまま動かす」だけ。Reactフロントは実験に不要。

---

## 0. 事前に研究室管理者へ確認

- **EC2 を起動してよいか**（許可されるインスタンス種別・リージョンの制約）
- **IAMロールを作成/アタッチしてよいか**（できなければ管理者に依頼）
- リージョンは **ap-northeast-1（東京）** を想定

---

## 1. IAMロールを用意（Bedrock 権限・キーレスの肝）

EC2 にロールを付けると、コンテナ内の boto3 が**自動で認証**します（`.env` にAWSキー不要）。

1. IAM コンソール → **ロール** → **ロールを作成**
2. 信頼されたエンティティ：**AWS のサービス → EC2**
3. 権限ポリシー：手軽さ優先なら **`AmazonBedrockFullAccess`**（最小権限にするなら `bedrock:InvokeModel` を含むカスタムポリシー）
4. ロール名（例：`bedrock-research-ec2`）を付けて作成

---

## 2. EC2 インスタンスを起動

- リージョン：**ap-northeast-1**
- AMI：**Ubuntu Server 22.04 / 24.04 LTS**
- インスタンスタイプ：**CPUのみでOK**（推論はBedrock側）。`t3.large`（2vCPU/8GB）程度が目安。ビルド/Chromaに余裕を持つなら `t3.xlarge`。
- ストレージ：**30GB 以上**（Dockerイメージ＋Chroma）
- ネットワーク：パブリックサブネット（インターネット接続あり）
- セキュリティグループ：**インバウンドは SSH(22) を自分のIPのみ**。8000/3000 は実験に不要なので開けない。
- **IAMインスタンスプロファイル**：手順1で作ったロールをアタッチ
- **重要（IMDSホップ制限）**：詳細設定で **メタデータの応答ホップ制限を 2** にする（`HttpPutResponseHopLimit=2`）。Dockerコンテナからインスタンスロールを取得するのに必要。
  - 起動後に変える場合（CLI例）：
    ```bash
    aws ec2 modify-instance-metadata-options --instance-id i-xxxx \
      --http-put-response-hop-limit 2 --http-tokens required --region ap-northeast-1
    ```
- キーペア（.pem）を作成/選択（SSH用）

---

## 3. SSH 接続

```bash
ssh -i /path/to/key.pem ubuntu@<EC2のパブリックIP>
```

---

## 4. Docker / git のインストール（Ubuntu）

```bash
sudo apt update
curl -fsSL https://get.docker.com | sudo sh          # Docker + compose plugin
sudo usermod -aG docker $USER                         # sudoなしでdocker実行
sudo apt install -y git
exit                                                  # 一度ログアウト→再SSHでグループ反映
```
再接続後に確認：
```bash
docker --version && docker compose version && git --version
```

---

## 5. リポジトリを取得

公開リポジトリなのでそのまま：
```bash
git clone https://github.com/fuharu/research.git
cd research
```

---

## 6. `.env` を作成（AWSキーは書かない＝ロールが供給）

```bash
cat > .env <<'EOF'
# LLMプロバイダ
LLM_PROVIDER=bedrock
EMBEDDING_PROVIDER=bedrock

# Bedrock（東京は推論プロファイルが必要なことが多いので apac. 付きを既定に）
BEDROCK_MODEL_ID=apac.anthropic.claude-3-5-haiku-20241022-v1:0
BEDROCK_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0
AWS_REGION=ap-northeast-1

# バックエンドはモックのまま（バグ注入の再現性のため）
USE_MOCK_GEMINI=true

# 埋め込みバージョン（Bedrockに切替えたのでコレクションは自動分離される）
EMBEDDING_VERSION=20250301
EOF
```
> `AWS_ACCESS_KEY_ID` 等は**書かない**。空ならコンテナはIMDS経由でインスタンスロールを使う。
> 接続テストで「inference profile が必要」「model not found」が出たら、コンソールのモデルカタログ（東京）で正確なIDを確認し `BEDROCK_MODEL_ID` を調整。

---

## 7. ビルド & 接続テスト

```bash
docker compose build agent                 # boto3 等を入れてビルド
docker compose up -d backend mock_gemini   # バックエンド(モック)起動
# Bedrock 接続テスト（IAMロールで認証される）
docker compose run --rm agent python -c \
"import sys; sys.path.append('/agent'); import reflection_engine as r; print(r._call_gemini('Reply with one word: hello'))"
```
`('hello', 整数)` が返れば成功。
- `AccessDenied` → ロールの権限/アタッチを確認。
- 認証情報が拾えない（NoCredentials）→ **IMDSホップ制限=2** になっているか確認（手順2）。

---

## 8. 実験を放置実行（tmux 推奨）

SSHを切っても走り続けるよう `tmux` を使う：
```bash
sudo apt install -y tmux
tmux new -s exp                            # セッション開始
# ↓ベースライン汚染を防ぐおまじない（前回の修正残りを戻す）
git checkout -- app/routers/tasks.py app/schemas/task.py evaluation/mock_gemini_server.py
rm -f app/routers/*.bak app/schemas/*.bak evaluation/*.bak

# パイロット
docker compose run --rm agent python /evaluation/pilot_warm_cold.py
# 本実験（準備できたら）
# docker compose run --rm agent python /evaluation/run_experiments.py
```
- デタッチ：`Ctrl+b` → `d`（実験は走り続ける）
- 再アタッチ：`tmux attach -t exp`
- 結果CSVは1試行ごとに `results/` に保存される（途中で切れても残る）

---

## 9. 結果の回収

ローカルPCから取得：
```bash
scp -i /path/to/key.pem ubuntu@<EC2のIP>:~/research/results/pilot_warm_cold.csv .
```
（大量に貯めるなら S3 に上げる：`aws s3 cp results/ s3://<bucket>/results/ --recursive`）

---

## 10. コスト管理（重要）

- 実験していない間は **必ずインスタンスを停止（Stop）**。停止中はEC2の計算課金は止まる（EBSストレージ代のみ）。
- 完全に不要になったら **Terminate**（削除）。Stop=一時停止、Terminate=破棄の違いに注意。
- Bedrock も従量課金。EC2＋Bedrockの二重課金になる点を意識（研究室負担でも使い終わったら止める）。

---

## 11. トラブルシューティング早見表

| 症状 | 原因/対処 |
|---|---|
| `NoCredentialsError` / ロールが拾えない | IMDSホップ制限を**2**に（手順2）。ロールがアタッチされているか確認 |
| `AccessDeniedException` | ロールに `bedrock:InvokeModel` 権限が無い。ポリシー確認 |
| `model not found` / `inference profile required` | 東京で使えるIDか確認。`apac.` プレフィックス付きに変更 |
| `ThrottlingException` | コード側でリトライ済み。続くならBedrockのクォータ確認 |
| ディスク不足 | EBSを増やす / `docker system prune` で不要イメージ削除 |
| success が全部0 | `USE_MOCK_GEMINI=true`（バックエンドがモック）か、ベースラインを `git checkout` したか確認 |

---

## まとめ

- **キーレス（IAMロール）＋放置実行（tmux）＋結果は逐次保存**、が今回の構成の要点。
- ローカルで悩んでいた「認証情報・PCクラッシュ・負荷」が一気に解消する。
- まずパイロットをEC2で1回通し、問題なければ本実験を放置で回す。
