# -*- coding: utf-8 -*-
"""PChome 商品價格分析 (Streamlit)

執行方式：streamlit run app.py
"""
import re
import time
from datetime import datetime
from urllib.parse import quote

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_URL = "https://ecshweb.pchome.com.tw/search/v3.3/all/results"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

st.set_page_config(page_title="PChome 商品價格分析", page_icon="🛒", layout="wide")


# ---------------------------------------------------------------- 爬蟲
@st.cache_data(show_spinner=False, ttl=600)
def fetch_page(keyword: str, page: int) -> list:
    """抓取單一頁面，回傳商品 list。"""
    url = f"{API_URL}?q={quote(keyword)}&page={page}&sort=sale/dc"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json().get("prods") or []


def crawl(keyword: str, pages: int, delay: float) -> pd.DataFrame:
    frames = []
    progress = st.progress(0.0, text="開始爬取…")
    for i in range(1, pages + 1):
        progress.progress((i - 1) / pages, text=f"正在爬取第 {i}/{pages} 頁…")
        try:
            prods = fetch_page(keyword, i)
        except (requests.RequestException, ValueError) as e:
            st.warning(f"第 {i} 頁抓取失敗：{e}")
            break
        if not prods:
            st.info(f"第 {i} 頁沒有資料，停止爬取。")
            break
        frames.append(pd.DataFrame(prods))
        if i < pages:
            time.sleep(delay)  # 禮貌性延遲，避免被封鎖
    progress.progress(1.0, text="爬取完成")
    progress.empty()
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------- 資料處理
def extract_brand(name: str) -> str:
    """從商品名稱擷取【品牌】，沒有則歸為「其他」。"""
    m = re.search(r"[【\[](.+?)[】\]]", str(name))
    return m.group(1).strip() if m else "其他"


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["name", "price"]].copy()
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out = out.dropna(subset=["price"]).reset_index(drop=True)
    out["brand"] = out["name"].map(extract_brand)

    bins = [0, 500, 1000, 1500, 2000, 3000, 5000, float("inf")]
    labels = ["<500", "500-999", "1000-1499", "1500-1999",
              "2000-2999", "3000-4999", "5000+"]
    out["price_range"] = pd.cut(out["price"], bins=bins, labels=labels,
                                right=False).astype(str)
    return out


# ---------------------------------------------------------------- 介面
st.title("🛒 PChome 商品價格分析")

with st.sidebar:
    st.header("搜尋設定")
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=2, step=1)
    delay = st.slider("每頁間隔秒數", 0.0, 10.0, 2.0, 0.5,
                      help="間隔太短可能被網站封鎖")
    top_n = st.slider("折線圖顯示前 N 筆", 10, 500, 70, 10)
    run = st.button("🔍 開始爬取", type="primary", use_container_width=True)

if run:
    if not keyword.strip():
        st.error("請輸入產品名稱")
        st.stop()
    raw = crawl(keyword.strip(), int(pages), delay)
    if raw.empty:
        st.error("沒有抓到任何資料，請換個關鍵字或稍後再試。")
        st.stop()
    st.session_state["raw"] = raw
    st.session_state["keyword"] = keyword.strip()

if "raw" not in st.session_state:
    st.info("請在左側輸入產品名稱與頁數，然後按「開始爬取」。")
    st.stop()

raw = st.session_state["raw"]
kw = st.session_state["keyword"]
df = prepare(raw)

if df.empty:
    st.error("資料中沒有有效的價格欄位。")
    st.stop()

# ---- 統計
avg_price = df["price"].mean()
c1, c2, c3, c4 = st.columns(4)
c1.metric("商品數量", f"{len(df):,}")
c2.metric("平均價格", f"{avg_price:,.0f}")
c3.metric("最高價格", f"{df['price'].max():,.0f}")
c4.metric("最低價格", f"{df['price'].min():,.0f}")

tab_line, tab_pie, tab_sun, tab_data = st.tabs(
    ["📈 折線圖", "🥧 圓餅圖", "☀️ 旭日圖", "📋 資料表"]
)

# ---- 折線圖
with tab_line:
    line_df = df.head(top_n).copy()
    line_df["編號"] = line_df.index + 1
    fig = px.line(line_df, x="編號", y="price", markers=True,
                  hover_data={"name": True, "price": ":,.0f", "編號": False},
                  labels={"price": "價格", "name": "商品名稱"},
                  title=f"PChome 電商網站上「{kw}」售價（前 {len(line_df)} 筆）")
    fig.add_hline(y=avg_price, line_dash="dash", line_color="red",
                  annotation_text=f"平均 {avg_price:,.0f}",
                  annotation_position="top left")
    fig.update_layout(height=550, xaxis_title="商品順序", yaxis_title="價格")
    st.plotly_chart(fig, use_container_width=True)

# ---- 圓餅圖
with tab_pie:
    order = ["<500", "500-999", "1000-1499", "1500-1999",
             "2000-2999", "3000-4999", "5000+"]
    pie_df = (df.groupby("price_range").size().reset_index(name="count"))
    pie_df["price_range"] = pd.Categorical(pie_df["price_range"],
                                           categories=order, ordered=True)
    pie_df = pie_df.sort_values("price_range")
    fig = px.pie(pie_df, names="price_range", values="count", hole=0.3,
                 title=f"「{kw}」價格區間分布")
    fig.update_traces(textinfo="percent+label+value")
    fig.update_layout(height=550)
    st.plotly_chart(fig, use_container_width=True)

# ---- 旭日圖
with tab_sun:
    max_brands = st.slider("每個價格區間最多顯示的品牌數（其餘歸為「其他」）",
                           3, 15, 6)
    sun_df = df.copy()
    # 每個價格區間只保留數量最多的前 N 個品牌，其餘合併
    keep = (sun_df.groupby(["price_range", "brand"]).size()
            .groupby(level=0, group_keys=False)
            .nlargest(max_brands).index)
    mask = sun_df.set_index(["price_range", "brand"]).index.isin(keep)
    sun_df.loc[~mask, "brand"] = "其他"
    sun_df = (sun_df.groupby(["price_range", "brand"]).size()
              .reset_index(name="count"))
    fig = px.sunburst(sun_df, path=["price_range", "brand"], values="count",
                      title=f"「{kw}」價格區間 → 品牌 分布")
    fig.update_traces(textinfo="label+value")
    fig.update_layout(height=650)
    st.plotly_chart(fig, use_container_width=True)

# ---- 資料表與下載
with tab_data:
    st.dataframe(df[["name", "brand", "price", "price_range"]],
                 use_container_width=True, height=500)
    fname = f"{datetime.now():%Y%m%d}_PCHOME_{kw}.csv"
    st.download_button("⬇️ 下載完整資料 CSV",
                       data=raw.to_csv(index=False).encode("utf-8-sig"),
                       file_name=fname, mime="text/csv")
