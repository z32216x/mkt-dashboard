# dashboard.py — Streamlit 儀表板(讀 GitHub data 分支的 Parquet,不用自架主機)
import io
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

from collect import SYMBOLS, safe_sym

st.set_page_config(page_title="台股決策儀表板", page_icon="📈", layout="wide")


def cfg(k, d=""):
    try:
        return st.secrets.get(k, d)
    except Exception:
        return d


st.sidebar.title("⚙️ 設定")
owner = st.sidebar.text_input("GitHub 帳號", value=cfg("GH_OWNER"))
repo = st.sidebar.text_input("Repo 名稱", value=cfg("GH_REPO", "mkt-dashboard"))
if st.sidebar.button("🔄 重新整理"):
    st.cache_data.clear()
    st.rerun()

if not owner or not repo:
    st.title("📈 台股決策儀表板")
    st.info("請在左側輸入 GitHub 帳號與 Repo 名稱(或在 Streamlit Cloud 的 Secrets 設 GH_OWNER / GH_REPO)。")
    st.stop()

BASE = f"https://raw.githubusercontent.com/{owner}/{repo}/data/"


@st.cache_data(ttl=300, show_spinner=False)
def fetch(base, rel):
    try:
        r = requests.get(base + rel, timeout=20)
        if r.status_code != 200:
            return None
        if rel.endswith(".parquet"):
            return pd.read_parquet(io.BytesIO(r.content))
        return r.json()
    except Exception:
        return None


def month_keys(n=2):
    now = datetime.now(timezone.utc)
    y, m, out = now.year, now.month, []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


def load_monthly(prefix, n=2):
    dfs = [fetch(BASE, f"{prefix}/{prefix}_{m}.parquet") for m in month_keys(n)]
    dfs = [d for d in dfs if d is not None and not d.empty]
    if not dfs:
        return None
    df = pd.concat(dfs, ignore_index=True)
    if "id" in df.columns:
        df = df.drop_duplicates("id", keep="last")
    return df


status = fetch(BASE, "meta/status.json") or {}
st.sidebar.caption("資料更新狀態(UTC)")
for k in ["last_run_utc", "last_quick_utc", "last_all_utc", "twse_date"]:
    if k in status:
        st.sidebar.caption(f"{k}: {status[k]}")

st.title("📈 台股決策儀表板(免費版)")
st.caption("免費資料多屬延遲或盤後資訊;內容僅供研究參考,非投資建議。")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["總覽", "走勢圖", "台股排行", "新聞", "PTT 熱門", "建議帳本"])

with tab1:
    keys = ["^TWII", "2330.TW", "TWD=X", "^SOX", "^VIX", "GC=F"]
    cols = st.columns(len(keys))
    for col, sym in zip(cols, keys):
        df = fetch(BASE, f"prices/{safe_sym(sym)}.parquet")
        with col:
            if df is None or len(df) < 2:
                st.metric(SYMBOLS[sym], "無資料")
                continue
            last, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
            pct = (last / prev - 1) * 100 if prev else 0.0
            st.metric(SYMBOLS[sym], f"{last:,.2f}", f"{pct:+.2f}%")

with tab2:
    name = st.selectbox("品種", list(SYMBOLS.values()))
    sym = [k for k, v in SYMBOLS.items() if v == name][0]
    df = fetch(BASE, f"prices/{safe_sym(sym)}.parquet")
    if df is None or df.empty:
        st.warning("尚無資料,請先到 GitHub Actions 手動跑一次 backfill。")
    else:
        days = st.selectbox("天數", [60, 180, 365, 1825, 100000], index=2,
                            format_func=lambda x: "全部" if x == 100000 else str(x))
        d = df.tail(days).set_index("Date")
        st.line_chart(d["Close"])
        st.bar_chart(d["Volume"])

with tab3:
    date = status.get("twse_date")
    df = fetch(BASE, f"twse/stocks_{date}.parquet") if date else None
    if df is None:
        st.warning("尚無台股盤後資料。")
    else:
        st.caption(f"資料日期:{df['date'].iloc[0]}")
        top = df.sort_values("TradeValue", ascending=False).head(20)
        st.bar_chart(top.set_index("Name")["TradeValue"].head(10))
        st.dataframe(top[["Code", "Name", "ClosingPrice", "TradeVolume", "TradeValue", "Transaction"]],
                     hide_index=True)

with tab4:
    df = load_monthly("news")
    if df is None:
        st.warning("尚無新聞資料。")
    else:
        df = df.sort_values(["importance", "published"], ascending=False).head(100)
        st.dataframe(df[["importance", "topic", "title", "source", "published", "link"]],
                     column_config={"link": st.column_config.LinkColumn("連結")},
                     hide_index=True)

with tab5:
    df = load_monthly("ptt")
    if df is None:
        st.warning("尚無 PTT 資料。")
    else:
        df = df.sort_values(["nrec_num", "posted"], ascending=False).head(60)
        st.dataframe(df[["nrec", "title", "author", "posted", "link"]],
                     column_config={"link": st.column_config.LinkColumn("連結")},
                     hide_index=True)

with tab6:
    df = fetch(BASE, "ledger/ledger.parquet")
    if df is None or df.empty:
        st.info("建議帳本目前是空的。之後每則推演(事件 → 品種 → 方向 → 信心度)都會寫進來,"
                "每天回填實際報酬,每週檢討命中率,驗證系統到底有沒有用。")
    else:
        st.dataframe(df, hide_index=True)
