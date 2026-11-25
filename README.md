# AI 市場決策大腦

免費、免自架主機的市場決策系統:台股/美股報價 + AI 預測 + 多人勝率追蹤 + 回測(含價格、成交量、新聞熱點)。

## 檔案說明
| 檔案 | 用途 | 狀態 |
|---|---|---|
| `ai-market.html` | 主儀表板:行情 + AI 預測 + 追蹤統計 + 回測 | ✅ 主要入口 |
| `collect.py` | 排程收集真實行情/新聞/成交量,寫入 data 分支 | ✅ 保留 |
| `.github/workflows/collect.yml` | 定時執行 collect.py | ✅ 保留 |
| `.github/workflows/compact.yml` | 每月壓縮 data 分支 | ✅ 保留 |
| `requirements.txt` | collect.py 的 Python 相依 | ✅ 保留 |

## 已停用(可刪除)
- `dashboard.py`(舊 Streamlit 儀表板,已被 ai-market.html 取代)
- `dashboard.html`(舊版前端,已被 ai-market.html 取代)

## 使用方式
1. 用瀏覽器直接打開 `ai-market.html`(或丟到 GitHub Pages 拿永久網址)。
2. 預設是「示範資料」,可立即體驗完整流程:預測 → 追蹤 → 結算勝率 → 回測。
3. 右上角 ⚙ 設定 → 貼上你的 **Gemini API Key**(AIza 開頭)→ 用真實 AI 預測。
4. (選填)在設定裡填 GitHub 帳號 + repo → 按「連接」,載入 collect.py 收集的真實行情。

## 安全提醒
- API Key 只存在你的瀏覽器(localStorage),不會上傳、不會寫進程式碼。
- 不要把 Key 貼到對話、公開場合,或 commit 進 repo。
- 曾在對話中貼過的 Key,請到 aistudio.google.com 撤銷並重新產生。

## 免責
免費/示範資料多為延遲資訊;本系統僅供研究參考,非投資建議。
