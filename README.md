# ETH シグナル通知Bot(GitHub Actions版)

パソコンがスリープ/シャットダウンしていても、GitHub側のサーバーが定期的にETH価格を取得してシグナルを判定し、メール・LINEに通知します。

## できること

- 15分ごとにCoinGeckoからETH価格を取得
- SMA / ボリンジャーバンド / RSI / MACD からシグナル(BUY / SELL / HOLD)を判定
- 前回と判定が変わったときだけ通知(無駄な通知を防ぐ)
- メール(SMTP)・LINE(Messaging API ブロードキャスト配信)の両方に対応

## セットアップ手順

### 1. GitHubリポジトリを作る
1. GitHubで新しいリポジトリを作成(Public/Privateどちらでも可。Privateの場合はActionsの実行時間に月次の無料枠上限があります)
2. このフォルダの中身(`check_eth_signal.py` / `requirements.txt` / `last_signal.json` / `.github/workflows/eth-signal.yml` / このREADME)をそのままリポジトリ直下にアップロード(GitHubの「Add file」→「Upload files」でドラッグ&ドロップでOK)

### 2. メール通知の準備(Gmailの例)
1. Googleアカウントで2段階認証を有効にする
2. 「アプリパスワード」を発行する(https://myaccount.google.com/apppasswords)
3. 発行された16桁のパスワードを控えておく(これは通常のログインパスワードとは別物です)

Gmail以外のプロバイダでも、SMTPのホスト名・ポート番号・ユーザー名・パスワードが分かれば利用できます。

### 3. LINE通知の準備
1. [LINE Developers](https://developers.line.biz/) にログインし、新規プロバイダー→Messaging APIチャネルを作成
2. チャネル基本設定の「チャネルアクセストークン(長期)」を発行してコピー
3. 作成したチャネルの公式アカウントを、自分のLINEアプリで友だち追加(チャネル基本設定のQRコードから追加できます)
4. このBotはブロードキャスト配信(友だち全員に送信)を使うため、ユーザーIDの取得は不要です。友だちが自分だけであれば、実質的に自分専用の通知になります。

### 4. GitHubにSecretsを登録する
リポジトリの `Settings → Secrets and variables → Actions → New repository secret` から、以下を登録してください(使わない通知手段の項目は登録不要です)。

| Secret名 | 内容 |
|---|---|
| `SMTP_HOST` | 例: `smtp.gmail.com` |
| `SMTP_PORT` | 例: `587` |
| `SMTP_USER` | 送信元メールアドレス |
| `SMTP_PASS` | アプリパスワード |
| `TO_EMAIL` | 通知を受け取りたいメールアドレス |
| `LINE_CHANNEL_TOKEN` | LINEのチャネルアクセストークン |

メールだけ使う場合は `ENABLE_LINE` を、LINEだけ使う場合は `ENABLE_EMAIL` を、`.github/workflows/eth-signal.yml` 内で `false` に変更してください。

### 5. 動作確認
1. リポジトリの「Actions」タブを開く
2. 「ETH Signal Check」ワークフローを選択し、「Run workflow」で手動実行
3. ログでシグナル判定結果と、通知の送信結果を確認
4. 問題なければ、あとは15分ごとに自動実行されます

## 注意事項

- GitHub Actionsの `schedule` は正確な時刻を保証しないため、混雑時は数分〜十数分ずれることがあります。
- 無料枠は Public リポジトリなら無制限、Private リポジトリは月2,000分までです(15分間隔・1回数十秒の実行であれば十分収まります)。
- これは投資助言ではありません。シグナルはあくまで参考情報としてご利用ください。
