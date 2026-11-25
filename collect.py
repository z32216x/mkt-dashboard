# collect.py — 市場資料收集器(免費版,Parquet 儲存,寫進 data 分支)
# 用法:python collect.py --mode backfill|quick|all|prices|news|ptt|twse|prune
import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

SYMBOLS = {
    "^TWII": "台股加權", "2330.TW": "台積電", "0050.TW": "元大台灣50",
    "^GSPC": "S&P500", "^IXIC": "那斯達克", "^SOX": "費城半導體",
    "^VIX": "VIX恐慌指數", "TSM": "台積電ADR",
    "^N225": "日經225", "^KS11": "韓國KOSPI", "^HSI": "恆生",
    "000001.SS": "上證指數", "^GDAXI": "德國DAX",
    "TWD=X": "美元/台幣", "DX-Y.NYB": "美元指數", "JPY=X": "美元/日圓",
    "CNH=X": "美元/離岸人民幣", "EURUSD=X": "歐元/美元",
    "^TNX": "美債10年殖利率", "CL=F": "WTI原油", "GC=F": "黃金", "HG=F": "銅",
}

NEWS_TOPICS = {
    "台股": "台股", "台積電": "台積電", "台幣": "台幣 匯率",
    "Fed": "Fed 利率", "油價": "油價", "黃金": "黃金 價格", "費半": "費城半導體",
}

# 簡單的關鍵字重要性評分(之後可換成 LLM 評分)
KEY_WEIGHTS = [
    (r"升息|降息|利率決策|央行|Fed|聯準會", 3),
    (r"戰爭|軍事|制裁|關稅|貿易戰", 3),
    (r"財報|法說|營收|獲利|EPS", 2),
    (r"外資|法人|買賣超", 2),
    (r"AI|輝達|Nvidia|台積電|2330", 2),
    (r"暴跌|崩|熔斷|漲停|跌停|創新高|創新低", 2),
]

LEDGER_COLS = ["ts_utc", "event_id", "event_title", "symbol", "direction",
               "horizon_days", "confidence", "rationale", "model_version",
               "outcome_checked", "ret_1d", "ret_5d", "hit"]


def now_utc():
    return datetime.now(timezone.utc)


def safe_sym(sym):
    return re.sub(r"[^A-Za-z0-9]+", "_", sym)


def save_df(df, relpath, dedup=None, sort=None):
    """合併舊檔、去重、排序後寫出;內容沒變就跳過寫檔(省 repo 空間)。"""
    p = DATA_DIR / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        old = pd.read_parquet(p)
        merged = pd.concat([old, df], ignore_index=True)
        if dedup:
            merged = merged.drop_duplicates(subset=dedup, keep="last")
        if sort:
            merged = merged.sort_values(sort).reset_index(drop=True)
        try:
            if merged.equals(old):
                return len(merged)
        except Exception:
            pass
        df = merged
    else:
        if dedup:
            df = df.drop_duplicates(subset=dedup, keep="last")
        if sort:
            df = df.sort_values(sort).reset_index(drop=True)
    df.to_parquet(p, index=False)
    return len(df)


def update_status(**kw):
    p = DATA_DIR / "meta" / "status.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    s = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    s.update(kw)
    s["last_run_utc"] = now_utc().isoformat(timespec="seconds")
    p.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def score_text(t):
    s = 1
    for pat, w in KEY_WEIGHTS:
        if re.search(pat, t or "", re.I):
            s += w
    return min(s, 10)


def parse_nrec(t):
    t = (t or "").strip()
    if t == "爆":
        return 100
    if t.startswith("X"):
        n = t[1:]
        if n in ("X", ""):
            return -100
        return -10 * (int(n) if n.isdigit() else 10)
    try:
        return int(t)
    except ValueError:
        return 0


def collect_prices(backfill=False):
    import yfinance as yf
    ok, fail = 0, []
    for sym in SYMBOLS:
        try:
            h = yf.Ticker(sym).history(period="10y" if backfill else "5d",
                                       interval="1d", auto_adjust=False)
            if h.empty:
                raise ValueError("no data")
            df = h.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
            df["Date"] = pd.to_datetime(df["Date"], utc=True).dt.tz_localize(None).dt.normalize()
            df["symbol"] = sym
            save_df(df, f"prices/{safe_sym(sym)}.parquet", dedup=["symbol", "Date"], sort=["Date"])
            ok += 1
        except Exception as e:
            fail.append(f"{sym}({e})")
        time.sleep(1)
    print(f"[prices] ok={ok} fail={fail}")


def collect_twse():
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        r = requests.get(url, headers=UA, timeout=30)
    except requests.exceptions.SSLError:
        import urllib3
        urllib3.disable_warnings()
        r = requests.get(url, headers=UA, timeout=30, verify=False)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise ValueError("TWSE 回傳空資料(可能尚未更新)")
    df = pd.DataFrame(rows)
    ad = str(int(str(df["Date"].iloc[0])) + 19110000)  # 民國年轉西元
    d = datetime.strptime(ad, "%Y%m%d").date()
    for c in ["TradeVolume", "TradeValue", "OpeningPrice", "HighestPrice",
              "LowestPrice", "ClosingPrice", "Transaction"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df["date"] = d.isoformat()
    p = DATA_DIR / "twse" / f"stocks_{d:%Y%m%d}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    update_status(twse_date=f"{d:%Y%m%d}")
    print(f"[twse] {d} 共 {len(df)} 檔")


def collect_news():
    import feedparser
    rows = []
    for topic, q in NEWS_TOPICS.items():
        try:
            url = ("https://news.google.com/rss/search?q=" + requests.utils.quote(q)
                   + "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
            feed = feedparser.parse(requests.get(url, headers=UA, timeout=20).content)
            for e in feed.entries:
                pp = getattr(e, "published_parsed", None)
                pub = datetime(*pp[:6], tzinfo=timezone.utc) if pp else now_utc()
                link = e.get("link", "")
                src = e.get("source")
                rows.append({
                    "id": hashlib.md5(link.encode()).hexdigest(),
                    "topic": topic,
                    "title": e.get("title", ""),
                    "link": link,
                    "source": src.get("title", "") if isinstance(src, dict) else "",
                    "published": pub.isoformat(),
                    "month": pub.strftime("%Y%m"),
                    "importance": score_text(e.get("title", "")),
                })
        except Exception as ex:
            print(f"[news] FAIL {topic}: {ex}")
        time.sleep(1)
    if rows:
        df = pd.DataFrame(rows)
        for m, g in df.groupby("month"):
            n = save_df(g.drop(columns=["month"]), f"news/news_{m}.parquet",
                        dedup=["id"], sort=["published"])
            print(f"[news] {m}: {n} 則")


def collect_ptt(pages=3):
    from bs4 import BeautifulSoup
    s = requests.Session()
    s.cookies.set("over18", "1", domain="www.ptt.cc")
    url = "https://www.ptt.cc/bbs/Stock/index.html"
    rows = []
    for _ in range(pages):
        try:
            r = s.get(url, headers=UA, timeout=20)
            r.raise_for_status()
        except Exception as ex:
            print(f"[ptt] FAIL {ex}")
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for ent in soup.select("div.r-ent"):
            a = ent.select_one("div.title a")
            if not a:
                continue
            href = a.get("href", "")
            link = "https://www.ptt.cc" + href
            m = re.search(r"M\.(\d{10})\.A", href)
            posted = datetime.fromtimestamp(int(m.group(1)), timezone.utc) if m else now_utc()
            nrec_el = ent.select_one("div.nrec span")
            nrec = nrec_el.get_text(strip=True) if nrec_el else "0"
            author_el = ent.select_one(".author")
            rows.append({
                "id": hashlib.md5(link.encode()).hexdigest(),
                "title": a.get_text(strip=True),
                "link": link,
                "author": author_el.get_text(strip=True) if author_el else "",
                "nrec": nrec,
                "nrec_num": parse_nrec(nrec),
                "posted": posted.isoformat(),
                "month": posted.strftime("%Y%m"),
            })
        prev = [a for a in soup.select("a.btn.wide") if "上頁" in a.get_text()]
        if not prev:
            break
        url = "https://www.ptt.cc" + prev[0]["href"]
        time.sleep(1)
    if rows:
        df = pd.DataFrame(rows)
        for m, g in df.groupby("month"):
            n = save_df(g.drop(columns=["month"]), f"ptt/ptt_{m}.parquet",
                        dedup=["id"], sort=["posted"])
            print(f"[ptt] {m}: {n} 篇")


def init_ledger():
    p = DATA_DIR / "ledger" / "ledger.parquet"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({c: pd.Series(dtype="object") for c in LEDGER_COLS}).to_parquet(p, index=False)
        print("[ledger] 已建立空白建議帳本")


def prune(days=120):
    cutoff = now_utc() - timedelta(days=days)
    d = DATA_DIR / "twse"
    if d.exists():
        for p in d.glob("stocks_*.parquet"):
            try:
                t = datetime.strptime(p.stem.split("_")[1], "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if t < cutoff:
                p.unlink()
                print(f"[prune] 刪除 {p.name}")


def run_step(name, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except Exception as e:
        print(f"FAIL {name}: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="quick",
                    choices=["backfill", "quick", "all", "prices", "news", "ptt", "twse", "prune"])
    args = ap.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    m = args.mode
    if m == "backfill":
        run_step("prices", collect_prices, backfill=True)
        run_step("twse", collect_twse)
        run_step("news", collect_news)
        run_step("ptt", collect_ptt)
        init_ledger()
    elif m == "quick":
        run_step("news", collect_news)
        run_step("ptt", collect_ptt)
        run_step("prices", collect_prices)
    elif m == "all":
        run_step("twse", collect_twse)
        run_step("news", collect_news)
        run_step("ptt", collect_ptt)
        run_step("prices", collect_prices)
    elif m == "prices":
        run_step("prices", collect_prices)
    elif m == "news":
        run_step("news", collect_news)
    elif m == "ptt":
        run_step("ptt", collect_ptt)
    elif m == "twse":
        run_step("twse", collect_twse)
    elif m == "prune":
        prune()
    update_status(**{f"last_{m}_utc": now_utc().isoformat(timespec="seconds")})
    print("done:", m)
