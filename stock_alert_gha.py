#!/usr/bin/env python3
"""
Stock Alert — versione GitHub Actions
Eseguito ogni 5 minuti dal workflow .github/workflows/stock_alert.yml
Credenziali lette da variabili d'ambiente (GitHub Secrets).
"""
# v1.1
import os, json, re, requests, feedparser
import yfinance as yf
from datetime import datetime, date, time as dt_time
import pytz

# ─── CONFIGURAZIONE ────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID        = os.environ["CHAT_ID"]
STATE_FILE     = "stock_state.json"
THRESHOLD      = 0.005   # 0.5%

STOCKS = {
    "BAMI.MI": "Banco BPM",
    "CNH.MI": "CNH Industrial",
    "PRT.MI":  "Esprinet",
    "AMP.MI":  "Amplifon",
}

ROME_TZ = pytz.timezone("Europe/Rome")
SEP     = "━━━━━━━━━━━━━━━━━━━━━━━━"
THIN    = "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─"
# ───────────────────────────────────────────────────────────


def log(msg):
    print(f"[{datetime.now(ROME_TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


def send_telegram(text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15
        )
        if not r.ok:
            log(f"Telegram error: {r.status_code}")
    except Exception as e:
        log(f"Telegram exception: {e}")


def get_price(ticker):
    try:
        hist = yf.Ticker(ticker).history(period="1d", interval="1m")
        if hist.empty:
            return None, None, None, None
        return (round(float(hist["Close"].iloc[-1]), 4),
                round(float(hist["Open"].iloc[0]),  4),
                round(float(hist["High"].max()),     4),
                round(float(hist["Low"].min()),      4))
    except Exception as e:
        log(f"Price error {ticker}: {e}")
        return None, None, None, None


def get_news(company):
    query = company.replace(" ", "+") + "+borsa+azioni"
    url   = f"https://news.google.com/rss/search?q={query}&hl=it&gl=IT&ceid=IT:it"
    try:
        feed = feedparser.parse(url)
        arts = []
        for e in feed.entries[:4]:
            src = getattr(e, "source", {})
            src = src.get("title", "") if isinstance(src, dict) else ""
            summary = re.sub(r"<[^>]+>", "", getattr(e, "summary", ""))[:220]
            arts.append({"title": e.get("title",""), "source": src,
                         "link": e.get("link",""), "summary": summary})
        return arts
    except Exception as ex:
        log(f"News error {company}: {ex}")
        return []


def news_summary(arts):
    if not arts:
        return "Nessuna notizia rilevante trovata al momento."
    titles = [a["title"] for a in arts[:3] if a["title"]]
    return "Principali temi: " + " — ".join(titles) + "."


def forecast_and_advice(change_pct, current, arts):
    n = len(arts); strong = abs(change_pct) >= 1.5
    if change_pct >= 0:
        ph = round(current*(1.008 if strong else 1.004), 3)
        pl = round(current*0.997, 3)
        fascia = f"€{pl:.3f} – €{ph:.3f}"
        fcast  = (f"Forte momentum rialzista con {n} articoli in circolazione. "
                  f"Possibile chiusura vicino ai massimi.\n📐 Fascia attesa: <b>{fascia}</b>"
                  if strong else
                  f"Movimento positivo contenuto. Trend al rialzo da confermare.\n"
                  f"📐 Fascia attesa: <b>{fascia}</b>")
        azione  = ("Mantieni la posizione. Nuovo ingresso solo su pull-back."
                   if strong else "Posizione da tenere. Attendi conferma.")
        monitor = (f"Tenuta sopra €{round(current*0.997,3):.3f} conferma il trend."
                   if strong else "Volumi in calo = movimento in esaurimento.")
    else:
        ph = round(current*1.003, 3)
        pl = round(current*(0.992 if strong else 0.996), 3)
        fascia = f"€{pl:.3f} – €{ph:.3f}"
        fcast  = (f"Forte pressione ribassista con {n} articoli negativi. "
                  f"Possibile chiusura vicino ai minimi.\n📐 Fascia attesa: <b>{fascia}</b>"
                  if strong else
                  f"Leggero calo ancora contenuto. Possibile rimbalzo nel pomeriggio.\n"
                  f"📐 Fascia attesa: <b>{fascia}</b>")
        azione  = ("Valuta stop loss se sei in posizione. Nessun nuovo ingresso oggi."
                   if strong else "Monitora: se supera -1% rivaluta la posizione.")
        monitor = ("Dichiarazioni ufficiali dell'azienda nel pomeriggio."
                   if strong else "Controlla il settore per capire se è movimento generalizzato.")
    return fcast, azione, monitor


def format_alert(ticker, name, open_p, current, change_pct, arts, ref=None):
    sign   = "+" if change_pct >= 0 else ""
    arrow  = "📈" if change_pct >= 0 else "📉"
    colore = "🟢" if change_pct >= 0 else "🔴"
    tri    = "▲" if change_pct >= 0 else "▼"
    diff   = current - open_p
    icona  = "✅" if change_pct >= 0 else "⚠️"
    now_str = datetime.now(ROME_TZ).strftime("%H:%M")
    fcast, azione, monitor = forecast_and_advice(change_pct, current, arts)
    syn = news_summary(arts)
    msg  = f"{SEP}\n🏦  <b>{name.upper()}</b>\n     <code>{ticker}</code>\n{SEP}\n\n"
    msg += f"{arrow}  <b>ALERT  {sign}{change_pct:.2f}%</b>  ·  {now_str}\n\n"
    if ref is not None:
        change_5 = ((current - ref) / ref) * 100
        sign_5   = "+" if change_5 >= 0 else ""
        msg += f"  ⏱ Ultimi 5 min:  €{ref:.3f}  →  €{current:.3f}  ({sign_5}{change_5:.2f}%)\n"
    msg += f"  Apertura        Attuale\n"
    msg += f"  €{open_p:.3f}  →  <b>€{current:.3f}</b>  {tri}\n\n"
    msg += f"  {colore}  <b>{sign}{change_pct:.2f}%</b>   <b>{sign}€{diff:.3f}</b>\n\n"
    msg += f"{SEP}\n📰  NOTIZIE IN TEMPO REALE\n{SEP}\n\n<i>{syn}</i>\n\n"
    for a in arts[:3]:
        t = a["title"][:80] + ("…" if len(a["title"])>80 else "")
        msg += f"▸ <b>{t}</b>\n"
        if a["summary"]:
            msg += f"  <i>{a['summary'][:120]}{'…' if len(a['summary'])>120 else ''}</i>\n"
        msg += f"  <a href='{a['link']}'>→ {a['source'] or 'Fonte'}</a>\n\n"
    msg += f"{SEP}\n🔮  PREVISIONE CHIUSURA\n{SEP}\n\n{fcast}\n\n"
    msg += f"{SEP}\n{icona}  CONSIGLIO\n{SEP}\n\n<b>{azione}</b>\n\n"
    msg += f"📌 <i>Tieni d'occhio: {monitor}</i>"
    return msg


def format_eod(results):
    today_str = datetime.now(ROME_TZ).strftime("%d/%m/%Y")
    msg = f"{SEP}\n📊  <b>RIEPILOGO · {today_str}</b>\n{SEP}\n"
    for i, (ticker, name, open_p, current, high, low) in enumerate(results):
        change = ((current - open_p) / open_p) * 100
        diff   = current - open_p
        sign   = "+" if change >= 0 else ""
        arrow  = "📈" if change > 0.1 else ("📉" if change < -0.1 else "➡️")
        if change > 1.5:
            valut = "✅ Giornata positiva, chiusura vicina ai massimi."
            cons  = "Mantieni o valuta ingresso in apertura se consolida."
        elif change > 0.1:
            valut = "🟡 Leggero rialzo nel range normale."
            cons  = "Nessuna azione urgente. Monitora l'apertura di domani."
        elif change < -1.5:
            valut = "🔴 Giornata negativa con pressione di vendita."
            cons  = "Attenzione domani in apertura. Valuta stop loss se in posizione."
        elif change < -0.1:
            valut = "🟠 Leggero calo, nessun segnale allarmante."
            cons  = "Se continua domani, rivaluta la posizione."
        else:
            valut = "⚪️ Giornata laterale, nessun movimento significativo."
            cons  = "Nessuna azione necessaria."
        msg += f"\n🏦  <b>{name.upper()}</b>\n     <code>{ticker}</code>\n\n"
        msg += f"  {arrow}  <b>{sign}{change:.2f}%</b>   <b>{sign}€{diff:.3f}</b>\n"
        msg += f"  <b>€{open_p:.3f}</b>  →  <b>€{current:.3f}</b>\n"
        msg += f"  🔺 €{high:.3f}   🔻 €{low:.3f}\n\n"
        msg += f"  {valut}\n  👉 <i>{cons}</i>\n"
        if i < len(results) - 1:
            msg += f"\n{THIN}\n"
    msg += f"\n{SEP}\nBuona serata! 🌙"
    return msg


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def main():
    now   = datetime.now(ROME_TZ)
    t     = now.time()
    today = date.today().isoformat()

    log(f"=== Check delle {now.strftime('%H:%M')} ===")

    # Weekend: esci
    if now.weekday() >= 5:
        log("Weekend — nessuna azione.")
        return

    # Fuori orario: esci
    if not (dt_time(9, 0) <= t <= dt_time(17, 45)):
        log("Fuori orario di borsa — nessuna azione.")
        return

    state = load_state()

    # Reset per nuovo giorno
    if state.get("date") != today:
        log(f"Nuovo giorno: {today}")
        state = {"date": today}
        save_state(state)

    # Riepilogo fine giornata
    if dt_time(17, 35) <= t <= dt_time(17, 45):
        if not state.get("eod_sent"):
            log("Invio riepilogo fine giornata...")
            results = []
            for ticker, name in STOCKS.items():
                cur, op, hi, lo = get_price(ticker)
                if cur and op:
                    results.append((ticker, name, op, cur, hi, lo))
            if results:
                send_telegram(format_eod(results))
            state["eod_sent"] = True
            save_state(state)
        return

    # Check prezzi intraday
    for ticker, name in STOCKS.items():
        cur, op, hi, lo = get_price(ticker)
        if cur is None:
            log(f"Nessun dato per {ticker}")
            continue

        ref        = state.get(f"{ticker}_ref", op)
        change_pct = ((cur - ref) / ref) * 100
        log(f"{ticker}: €{cur:.3f}  ref=€{ref:.3f}  Δ={change_pct:+.3f}%")

        if abs(change_pct) >= 0.5:
            log(f"ALERT {ticker}: {change_pct:+.2f}%")
            arts             = get_news(name)
            change_from_open = ((cur - op) / op) * 100
            send_telegram(format_alert(ticker, name, op, cur, change_from_open, arts, ref=ref))

        state[f"{ticker}_ref"] = cur
        save_state(state)

    log("Check completato.")


if __name__ == "__main__":
    main()
