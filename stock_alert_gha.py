#!/usr/bin/env python3
"""
Stock Alert — Versione 2.2 Stateless (GitHub Actions)
Layout con Delta monetario (€) dei 5 minuti posizionato sotto le colonne.
"""

import os, json, re, requests, feedparser
import yfinance as yf
from datetime import datetime, date, timedelta, time as dt_time
import pytz

# ─── CONFIGURAZIONE ────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID        = os.environ["CHAT_ID"]
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
            return None, None, None, None, None
            
        current = round(float(hist["Close"].iloc[-1]), 4)
        open_p  = round(float(hist["Open"].iloc[0]),  4)
        high    = round(float(hist["High"].max()),     4)
        low     = round(float(hist["Low"].min()),      4)
        
        # Recupera il prezzo di circa 5 minuti fa (-6 index nel dataframe a 1m)
        idx_5min = max(-6, -len(hist))
        ref_5min = round(float(hist["Close"].iloc[idx_5min]), 4)
        
        return current, open_p, high, low, ref_5min
    except Exception as e:
        log(f"Price error {ticker}: {e}")
        return None, None, None, None, None


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


def format_alert(ticker, name, open_p, current, high, low, change_daily, change_5m, arts, ref):
    sign_5  = "+" if change_5m >= 0 else ""
    colore  = "🟢" if change_5m >= 0 else "🔴"
    arrow_5 = "⚡️"
    
    # Calcolo delta monetario 5 minuti
    diff_5m   = current - ref
    sign_5m_d = "+" if diff_5m >= 0 else ""
    
    sign_d  = "+" if change_daily >= 0 else ""
    arrow_d = "📈" if change_daily >= 0 else "📉"
    diff_d  = current - open_p
    icona   = "✅" if change_daily >= 0 else "⚠️"
    
    # Orari (Adesso e 5 minuti fa)
    now = datetime.now(ROME_TZ)
    time_now_str = now.strftime("%H:%M")
    time_5m_str  = (now - timedelta(minutes=5)).strftime("%H:%M")
    
    fcast, azione, monitor = forecast_and_advice(change_daily, current, arts)
    syn = news_summary(arts)
    
    # Costruzione del messaggio Telegram
    msg  = f"{SEP}\n🏦  <b>{name.upper()}</b>\n     <code>{ticker}</code>\n{SEP}\n\n"
    msg += f"{arrow_5}  <b>ALERT 5 MIN: {sign_5}{change_5m:.2f}%</b>\n\n"
    
    # Colonne Orario e Prezzo
    msg += f"🕒 <b>{time_5m_str}</b> (5 min fa)         🕒 <b>{time_now_str}</b> (Adesso)\n"
    msg += f"💶 €{ref:.3f}                    💶 <b>€{current:.3f}</b>\n"
    
    # Nuova riga con il delta monetario flash
    msg += f"💰 Spostamento flash: <b>{sign_5m_d}€{diff_5m:.3f}</b>\n\n"
    
    # Sezione Giornaliera
    msg += f"{arrow_d}  <b>Performance Giornaliera: {sign_d}{change_daily:.2f}%</b>\n"
    msg += f"  Apertura: €{open_p:.3f}  ·  Max: €{high:.3f}  ·  Min: €{low:.3f}\n"
    msg += f"  {colore}  Delta odierno: <b>{sign_d}€{diff_d:.3f}</b>\n\n"
    
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


def main():
    now   = datetime.now(ROME_TZ)
    t     = now.time()

    log(f"=== Check delle {now.strftime('%H:%M')} ===")

    if now.weekday() >= 5:
        log("Weekend — nessuna azione.")
        return

    if not (dt_time(9, 0) <= t <= dt_time(17, 45)):
        log("Fuori orario di borsa — nessuna azione.")
        return

    # Aspetta il secondo :55 del minuto per dati più stabili
    now = datetime.now(ROME_TZ)
    secondi_attesa = (55 - now.second) % 60
    if secondi_attesa > 0:
        log(f"Attendo {secondi_attesa}s per dati stabili...")
        import time
        time.sleep(secondi_attesa)
    
    if dt_time(17, 35) <= t < dt_time(17, 40):
        log("Invio riepilogo fine giornata...")
        results = []
        for ticker, name in STOCKS.items():
            cur, op, hi, lo, _ = get_price(ticker)
            if cur and op:
                results.append((ticker, name, op, cur, hi, lo))
        if results:
            send_telegram(format_eod(results))
        return

    for ticker, name in STOCKS.items():
        cur, op, hi, lo, ref = get_price(ticker)
        if cur is None:
            log(f"Nessun dato per {ticker}")
            continue

        change_5m = ((cur - ref) / ref) * 100
        log(f"{ticker}: €{cur:.3f}  ref_5m=€{ref:.3f}  Δ5m={change_5m:+.3f}%")

        if abs(change_5m) >= 0.5:
            log(f"ALERT ATTIVATO {ticker}: {change_5m:+.2f}% negli ultimi 5 min")
            arts = get_news(name)
            change_daily = ((cur - op) / op) * 100
            
            send_telegram(format_alert(ticker, name, op, cur, hi, lo, change_daily, change_5m, arts, ref))

    log("Check completato.")


if __name__ == "__main__":
    main()
