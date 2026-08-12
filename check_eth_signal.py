"""
ETH シグナルチェック & 通知スクリプト
GitHub Actions などのスケジューラーから定期実行することを想定しています。
"""
import os
import json
import smtplib
from email.mime.text import MIMEText

import requests

CG_BASE = "https://api.coingecko.com/api/v3"
STATE_FILE = "last_signal.json"


# ---------- 価格データ取得 ----------
def fetch_prices():
    """
    TIMEFRAME 環境変数で足の種類を切り替える。
      1h  : 過去30日分を時間足で取得(CoinGeckoの自動粒度)
      4h  : 過去90日分を時間足で取得し、4本ごとに束ねて4時間足を作る
      daily(既定): 過去120日分を日足で取得
    """
    timeframe = os.environ.get("TIMEFRAME", "1h").lower()

    if timeframe == "4h":
        r = requests.get(
            f"{CG_BASE}/coins/ethereum/market_chart",
            params={"vs_currency": "jpy", "days": 90},
            timeout=30,
        )
        r.raise_for_status()
        pts = r.json()["prices"]
        prices = [p[1] for p in pts[::4]]
    elif timeframe == "1h":
        r = requests.get(
            f"{CG_BASE}/coins/ethereum/market_chart",
            params={"vs_currency": "jpy", "days": 30},
            timeout=30,
        )
        r.raise_for_status()
        pts = r.json()["prices"]
        prices = [p[1] for p in pts]
    else:
        r = requests.get(
            f"{CG_BASE}/coins/ethereum/market_chart",
            params={"vs_currency": "jpy", "days": 120, "interval": "daily"},
            timeout=30,
        )
        r.raise_for_status()
        pts = r.json()["prices"]
        prices = [p[1] for p in pts]

    r2 = requests.get(
        f"{CG_BASE}/simple/price",
        params={"ids": "ethereum", "vs_currencies": "jpy", "include_24hr_change": "true"},
        timeout=30,
    )
    r2.raise_for_status()
    d2 = r2.json()["ethereum"]
    return prices, d2["jpy"], d2["jpy_24h_change"]


def sma(vals, period):
    out = [None] * len(vals)
    for i in range(period - 1, len(vals)):
        out[i] = sum(vals[i - period + 1 : i + 1]) / period
    return out


def ema_series(vals, period):
    n = len(vals)
    out = [None] * n
    start = next((i for i, v in enumerate(vals) if v is not None), None)
    if start is None or n - start < period:
        return out
    seed = sum(vals[start : start + period]) / period
    idx = start + period - 1
    out[idx] = seed
    prev = seed
    k = 2 / (period + 1)
    for i in range(idx + 1, n):
        prev = vals[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def stddev(vals, period, sma_arr):
    out = [None] * len(vals)
    for i in range(period - 1, len(vals)):
        m = sma_arr[i]
        s = sum((vals[j] - m) ** 2 for j in range(i - period + 1, i + 1))
        out[i] = (s / period) ** 0.5
    return out


def rsi(vals, period=14):
    out = [None] * len(vals)
    avg_g = avg_l = None
    gains = losses = 0
    for i in range(1, len(vals)):
        diff = vals[i] - vals[i - 1]
        if i <= period:
            if diff >= 0:
                gains += diff
            else:
                losses -= diff
            if i == period:
                avg_g = gains / period
                avg_l = losses / period
                out[i] = 100 if avg_l == 0 else 100 - (100 / (1 + avg_g / avg_l))
        else:
            up = diff if diff > 0 else 0
            down = -diff if diff < 0 else 0
            avg_g = (avg_g * (period - 1) + up) / period
            avg_l = (avg_l * (period - 1) + down) / period
            out[i] = 100 if avg_l == 0 else 100 - (100 / (1 + avg_g / avg_l))
    return out


def compute_all(prices):
    sma20 = sma(prices, 20)
    sma50 = sma(prices, 50)
    std20 = stddev(prices, 20, sma20)
    upper_bb = [(sma20[i] + 2 * std20[i]) if sma20[i] is not None else None for i in range(len(prices))]
    lower_bb = [(sma20[i] - 2 * std20[i]) if sma20[i] is not None else None for i in range(len(prices))]
    rsi_arr = rsi(prices, 14)
    e12 = ema_series(prices, 12)
    e26 = ema_series(prices, 26)
    macd_line = [(e12[i] - e26[i]) if (e12[i] is not None and e26[i] is not None) else None for i in range(len(prices))]
    signal_line = ema_series(macd_line, 9)
    hist = [
        (macd_line[i] - signal_line[i]) if (macd_line[i] is not None and signal_line[i] is not None) else None
        for i in range(len(prices))
    ]
    return {
        "sma20": sma20,
        "sma50": sma50,
        "upperBB": upper_bb,
        "lowerBB": lower_bb,
        "rsi": rsi_arr,
        "macdLine": macd_line,
        "signalLine": signal_line,
        "hist": hist,
    }


def generate_signal(prices, ind):
    n = len(prices) - 1
    reasons = []
    score = 0

    close, prev_close = prices[n], prices[n - 1]
    rsi_now = ind["rsi"][n]
    upper, lower = ind["upperBB"][n], ind["lowerBB"][n]
    sma20_now, sma20_prev = ind["sma20"][n], ind["sma20"][n - 1]
    hist_now, hist_prev = ind["hist"][n], ind["hist"][n - 1]

    if lower is not None and close < lower:
        score += 1
        reasons.append("価格がボリンジャーバンド下限を下回っています(売られすぎの可能性)")
    if upper is not None and close > upper:
        score -= 1
        reasons.append("価格がボリンジャーバンド上限を上回っています(買われすぎの可能性)")

    if rsi_now is not None:
        if rsi_now < 30:
            score += 1
            reasons.append(f"RSIが{rsi_now:.1f}で売られすぎ水準(30未満)です")
        if rsi_now > 70:
            score -= 1
            reasons.append(f"RSIが{rsi_now:.1f}で買われすぎ水準(70超)です")

    if hist_prev is not None and hist_now is not None:
        if hist_prev < 0 and hist_now >= 0:
            score += 1
            reasons.append("MACDヒストグラムがマイナスからプラスに転換しました(上昇の兆し)")
        if hist_prev > 0 and hist_now <= 0:
            score -= 1
            reasons.append("MACDヒストグラムがプラスからマイナスに転換しました(下降の兆し)")

    if sma20_prev is not None and sma20_now is not None:
        if prev_close <= sma20_prev and close > sma20_now:
            score += 1
            reasons.append("価格がSMA20を上抜けました")
        if prev_close >= sma20_prev and close < sma20_now:
            score -= 1
            reasons.append("価格がSMA20を下抜けました")

    signal_type = "HOLD"
    if score >= 2:
        signal_type = "BUY"
    elif score <= -2:
        signal_type = "SELL"

    if not reasons:
        reasons.append("明確なシグナルは検出されていません(様子見)")

    return {"type": signal_type, "score": score, "reasons": reasons}


def send_email(subject, body):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    to_email = os.environ["TO_EMAIL"]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_email

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(user, [to_email], msg.as_string())


def send_line(text):
    token = os.environ["LINE_CHANNEL_TOKEN"]
    r = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"messages": [{"type": "text", "text": text}]},
        timeout=30,
    )
    r.raise_for_status()


def notify_all(subject, body):
    if os.environ.get("ENABLE_EMAIL", "false").lower() == "true":
        try:
            send_email(subject, body)
            print("メール通知を送信しました")
        except Exception as e:
            print(f"メール送信エラー: {e}")

    if os.environ.get("ENABLE_LINE", "false").lower() == "true":
        try:
            send_line(body)
            print("LINE通知を送信しました")
        except Exception as e:
            print(f"LINE送信エラー: {e}")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
    else:
        data = {}
    return {
        "type": data.get("type"),
        "last_price": data.get("last_price"),
        "short_alerted": data.get("short_alerted", False),
        "day_alerted": data.get("day_alerted", False),
    }


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def check_price_alerts(current, change24h, state):
    short_pct_threshold = float(os.environ.get("PRICE_ALERT_SHORT_PCT", "1.5"))
    day_pct_threshold = float(os.environ.get("PRICE_ALERT_24H_PCT", "5"))

    messages = []

    last_price = state["last_price"]
    if last_price:
        short_pct = (current - last_price) / last_price * 100
        if abs(short_pct) >= short_pct_threshold:
            if not state["short_alerted"]:
                direction = "急騰" if short_pct > 0 else "急落"
                messages.append(
                    f"[価格急変アラート] 前回チェック時から{direction}: {short_pct:+.2f}%\n"
                    f"現在価格: {round(current):,}円"
                )
                state["short_alerted"] = True
        elif abs(short_pct) < short_pct_threshold * 0.5:
            state["short_alerted"] = False

    if abs(change24h) >= day_pct_threshold:
        if not state["day_alerted"]:
            direction = "上昇" if change24h > 0 else "下落"
            messages.append(
                f"[24時間アラート] 24時間で{direction}: {change24h:+.2f}%\n"
                f"現在価格: {round(current):,}円"
            )
            state["day_alerted"] = True
    elif abs(change24h) < day_pct_threshold * 0.5:
        state["day_alerted"] = False

    state["last_price"] = current
    return messages, state


def main():
    prices, current, change24h = fetch_prices()
    ind = compute_all(prices)
    signal = generate_signal(prices, ind)
    state = load_state()
    last_type = state["type"]

    print(f"現在価格: {round(current):,}円 (24h {change24h:.2f}%)")
    print(f"シグナル: {signal['type']} (スコア {signal['score']})")
    for r in signal["reasons"]:
        print(" -", r)

    notify_always = os.environ.get("NOTIFY_ALWAYS", "false").lower() == "true"

    # HOLDの時は通知しない。BUY/SELLに変化した時、またはNOTIFY_ALWAYSが有効な時のみ通知
    if signal["type"] != "HOLD" and (last_type != signal["type"] or notify_always):
        subject = f"ETHシグナル: {signal['type']}"
        body = (
            f"ETH価格: {round(current):,}円\n"
            f"判定: {signal['type']}\n"
            "理由:\n- " + "\n- ".join(signal["reasons"])
        )
        notify_all(subject, body)
        state["type"] = signal["type"]
    else:
        print("通知条件を満たしていません(HOLDまたは変化なし)。通知はスキップしました。")
        state["type"] = signal["type"]

    alert_messages, state = check_price_alerts(current, change24h, state)
    for msg in alert_messages:
        print(msg)
        notify_all("ETH価格急変アラート", msg)

    save_state(state)


if __name__ == "__main__":
    main()
