#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股日报 - 独立运行版
在 GitHub Actions 上定时执行，不依赖任何本地 CLI 工具
"""

import json
import re
import smtplib
import urllib.request
import urllib.parse
from datetime import datetime, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header

# ===================== 配置 =====================
SMTP_HOST = "smtp.qq.com"
SMTP_PORT = 465
FROM_ADDR = "3222607515@qq.com"
TO_ADDR = "3222607515@qq.com"
PASSWORD = "yvcbbwrnuoyfciga"

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def fetch_url(url, encoding="utf-8"):
    """简单 HTTP GET 请求"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read()
        return data.decode(encoding)


def parse_tencent_quote(raw):
    """解析腾讯股票行情接口返回的文本"""
    # 格式: v_sh000001="1~上证指数~3913.79~-82.37~-2.06~..."
    result = {}
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        # 提取引号内的内容
        m = re.search(r'"(.+)"', line)
        if not m:
            continue
        fields = m.group(1).split("~")
        if len(fields) < 32:
            continue
        code = fields[0]
        name = fields[1]
        price = fields[3]
        change = fields[31]
        change_pct = fields[32]
        try:
            result[code] = {
                "name": name,
                "price": float(price) if price else 0,
                "change": float(change) if change else 0,
                "change_pct": float(change_pct) if change_pct else 0,
            }
        except ValueError:
            continue
    return result


def get_index_quotes():
    """获取三大指数实时行情 (腾讯行情接口)"""
    codes = "sh000001,sz399001,sz399006"
    url = f"https://qt.gtimg.cn/q={codes}"
    raw = fetch_url(url, "gbk")
    return parse_tencent_quote(raw)


def get_market_changedist():
    """获取两市涨跌分布 - 使用腾讯全市场数据"""
    # 获取所有A股行情概览 - 用分时接口
    url = "https://push2.eastmoney.com/api/qt/clist/get?cb=&pn=1&pz=5000&po=1&np=1&fltt=2&invt=2&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f2,f3,f8,f12,f14"
    data_str = fetch_url(url)
    try:
        data = json.loads(data_str)
        total = data.get("data", {}).get("total", 0)
        diff = data.get("data", {}).get("diff", [])
        up = sum(1 for d in diff if d.get("f3", 0) > 0)
        down = sum(1 for d in diff if d.get("f3", 0) < 0)
        flat = total - up - down
        return {"up": up, "down": down, "flat": flat, "total": total}
    except:
        return {"up": "-", "down": "-", "flat": "-", "total": "-"}


def get_market_trade_data():
    """获取两市成交额"""
    url = "https://push2.eastmoney.com/api/qt/clist/get?cb=&pn=1&pz=2&po=1&np=1&fltt=2&invt=2&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields=f2,f3,f4,f12,f14"
    data_str = fetch_url(url)
    try:
        data = json.loads(data_str)
        diff = data.get("data", {}).get("diff", [])
        total_amount = sum(d.get("f4", 0) or 0 for d in diff)
        return total_amount
    except:
        return "-"


def get_index_flow_data():
    """获取指数分时数据中的资金流向"""
    # 使用腾讯指数资金流向API
    url = "https://qt.gtimg.cn/q=ff_sh000001"
    try:
        raw = fetch_url(url, "gbk")
        return raw[:200]  # 截取部分信息
    except:
        return ""


def get_sector_ranking():
    """获取板块排行 - 使用东方财富API"""
    # 行业板块涨幅榜
    url = "https://push2.eastmoney.com/api/qt/clist/get?cb=&pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fs=m:90+t:2&fields=f2,f3,f4,f12,f14"
    data_str = fetch_url(url)
    sectors = []
    try:
        data = json.loads(data_str)
        diff = data.get("data", {}).get("diff", [])
        for d in diff[:5]:
            sectors.append({
                "name": d.get("f14", ""),
                "change_pct": d.get("f3", 0),
                "amount": d.get("f4", 0),
            })
    except:
        pass
    return sectors


def get_market_news():
    """获取市场资讯 - 使用东方财富快讯"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f12,f14,f2,f3,f4&secids=1.000001,0.399001,0.399006"
    # 使用新浪新闻源的替代方案
    try:
        # 尝试获取新浪财经新闻头条
        news_url = "https://feed.mix.sina.com.cn/api/feed/get?listid=10&page=1&count=5&callback=&_=0"
        news_raw = fetch_url(news_url)
        data = json.loads(news_raw)
        items = data.get("result", {}).get("data", [])
        news_list = []
        for item in items[:5]:
            news_list.append({
                "time": item.get("ctime", ""),
                "title": item.get("title", ""),
            })
        return news_list
    except:
        return []


def generate_html(index_quotes, changedist, amount, sectors, news):
    """生成日报 HTML"""
    today = date.today()
    weekday = WEEKDAYS[today.weekday()]

    # 判断涨跌颜色
    def color(val):
        if val > 0:
            return "red"
        elif val < 0:
            return "green"
        return ""

    def fmt_num(n):
        if n == "-":
            return "-"
        return f"{n:,.0f}"

    def fmt_price(p):
        if p == "-":
            return "-"
        return f"{p:,.2f}"

    # 构建指数卡片
    index_cards = ""
    idx_map = {"sh000001": "上证指数", "sz399001": "深证成指", "sz399006": "创业板指"}
    for code, display_name in idx_map.items():
        d = index_quotes.get(code, {"price": "-", "change": 0, "change_pct": 0, "name": display_name})
        if isinstance(d["price"], str):
            index_cards += f"""
      <div class="index-card">
        <div class="name">{display_name}</div>
        <div class="price">-</div>
        <div class="change">数据获取中</div>
      </div>"""
        else:
            c = color(d["change"])
            index_cards += f"""
      <div class="index-card">
        <div class="name">{display_name}</div>
        <div class="price">{fmt_price(d['price'])}</div>
        <div class="change {c}">{fmt_num(d['change'])} <span class="{c}">{d['change_pct']:+.2f}%</span></div>
      </div>"""

    # 判断市场情绪
    if isinstance(changedist.get("up"), int) and isinstance(changedist.get("down"), int):
        total = changedist["up"] + changedist["down"] + changedist["flat"]
        up_ratio = changedist["up"] / total * 100 if total > 0 else 0
        if up_ratio >= 60:
            sentiment_class = "hot"
            sentiment_text = "🔥 市场情绪偏暖"
            sentiment_detail = f"上涨占比 {up_ratio:.0f}%"
        elif up_ratio >= 40:
            sentiment_class = "moderate"
            sentiment_text = "⚖️ 市场情绪中性"
            sentiment_detail = f"上涨占比 {up_ratio:.0f}%"
        else:
            sentiment_class = "cold"
            sentiment_text = "🌬️ 市场情绪偏冷"
            sentiment_detail = f"上涨占比 {up_ratio:.0f}%"
    else:
        sentiment_class = "moderate"
        sentiment_text = "📊 市场数据获取中"
        sentiment_detail = ""

    # 市场总览网格
    def val(v, unit=""):
        if isinstance(v, int):
            return f"{v:,}{unit}"
        return str(v)

    up_val = val(changedist.get("up", "-"))
    down_val = val(changedist.get("down", "-"))
    amount_str = fmt_num(amount) if isinstance(amount, (int, float)) else str(amount)
    flat_val = val(changedist.get("flat", "-"))

    # 板块表格
    sector_rows = ""
    for i, s in enumerate(sectors[:5], 1):
        c = color(s["change_pct"])
        sector_rows += f"""
        <tr><td>{i}</td><td>{s['name']}</td><td class="{c}">{s['change_pct']:+.2f}%</td></tr>"""

    # 新闻
    news_items = ""
    for n in news[:5]:
        news_items += f"""
      <li class="news-item">
        <span class="title">{n.get('title', '')}</span>
      </li>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股日报 {today}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Microsoft YaHei', 'PingFang SC', -apple-system, sans-serif; background: #f5f6fa; padding: 0; margin: 0; }}
.container {{ max-width: 640px; margin: 0 auto; background: #ffffff; }}
.header {{ background: linear-gradient(135deg, #c0392b, #e74c3c); color: white; padding: 32px 24px; text-align: center; }}
.header h1 {{ font-size: 28px; margin-bottom: 6px; letter-spacing: 2px; }}
.header .date {{ font-size: 14px; opacity: 0.9; }}
.section {{ padding: 20px 24px; }}
.section-title {{ font-size: 17px; font-weight: bold; color: #2c3e50; margin-bottom: 14px; padding-left: 10px; border-left: 4px solid #c0392b; }}
.index-grid {{ display: flex; gap: 10px; flex-wrap: wrap; }}
.index-card {{ flex: 1; min-width: 140px; background: #fafafa; border-radius: 10px; padding: 16px; text-align: center; border: 1px solid #eee; }}
.index-card .name {{ font-size: 13px; color: #7f8c8d; margin-bottom: 4px; }}
.index-card .price {{ font-size: 22px; font-weight: bold; color: #2c3e50; margin-bottom: 4px; }}
.index-card .change {{ font-size: 14px; }}
.index-card .change.red {{ color: #c0392b; }}
.index-card .change.green {{ color: #27ae60; }}
.meta-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }}
.meta-item {{ background: #fafafa; border-radius: 8px; padding: 14px; text-align: center; border: 1px solid #eee; }}
.meta-item .label {{ font-size: 12px; color: #7f8c8d; margin-bottom: 4px; }}
.meta-item .value {{ font-size: 18px; font-weight: bold; color: #2c3e50; }}
.sentiment {{ text-align: center; padding: 16px; margin: 0 24px 20px; border-radius: 10px; font-size: 16px; font-weight: bold; }}
.sentiment.cold {{ background: #e8f8f5; color: #27ae60; border: 1px solid #a3e4d7; }}
.sentiment.hot {{ background: #fdedec; color: #c0392b; border: 1px solid #f5b7b1; }}
.sentiment.moderate {{ background: #fef9e7; color: #d4ac0d; border: 1px solid #f9e79f; }}
.data-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.data-table th {{ background: #f0f0f0; color: #555; padding: 8px 6px; text-align: center; font-weight: 600; border-bottom: 2px solid #ddd; }}
.data-table td {{ padding: 8px 6px; text-align: center; border-bottom: 1px solid #eee; }}
.data-table .up {{ color: #c0392b; font-weight: bold; }}
.data-table .down {{ color: #27ae60; font-weight: bold; }}
.news-list {{ list-style: none; }}
.news-item {{ padding: 10px 0; border-bottom: 1px solid #f0f0f0; }}
.news-item:last-child {{ border-bottom: none; }}
.news-item .time {{ font-size: 11px; color: #95a5a6; }}
.news-item .title {{ font-size: 14px; color: #2c3e50; line-height: 1.5; }}
.footer {{ background: #2c3e50; color: #bdc3c7; padding: 20px 24px; text-align: center; font-size: 12px; line-height: 1.8; }}
.footer .legend {{ display: flex; justify-content: center; gap: 20px; margin-bottom: 10px; }}
.footer .legend-item {{ display: flex; align-items: center; gap: 4px; }}
.footer .legend-dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; }}
.footer .legend-dot.red {{ background: #c0392b; }}
.footer .legend-dot.green {{ background: #27ae60; }}
@media (max-width: 480px) {{
  .index-card {{ min-width: 100%; }}
}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📈 A股日报</h1>
    <p class="date">{today.year}年{today.month}月{today.day}日 {weekday}</p>
  </div>

  <div class="section">
    <div class="section-title">大盘指数</div>
    <div class="index-grid">{index_cards}</div>
  </div>

  <div class="section">
    <div class="section-title">市场总览</div>
    <div class="meta-grid">
      <div class="meta-item"><div class="label">两市成交额</div><div class="value">{amount_str}亿</div></div>
      <div class="meta-item"><div class="label">上涨家数</div><div class="value" style="color:#c0392b">{up_val}</div></div>
      <div class="meta-item"><div class="label">下跌家数</div><div class="value" style="color:#27ae60">{down_val}</div></div>
    </div>
  </div>

  <div class="sentiment {sentiment_class}">
    {sentiment_text} · {sentiment_detail}
  </div>

  <div class="section">
    <div class="section-title">行业涨幅 TOP5</div>
    <table class="data-table">
      <thead><tr><th>排名</th><th>行业</th><th>涨跌幅</th></tr></thead>
      <tbody>{sector_rows}</tbody>
    </table>
  </div>

  <div class="section">
    <div class="section-title">今日资讯</div>
    <ul class="news-list">{news_items}</ul>
  </div>

  <div class="footer">
    <div class="legend">
      <span class="legend-item"><span class="legend-dot red"></span> 上涨</span>
      <span class="legend-item"><span class="legend-dot green"></span> 下跌</span>
    </div>
    <p>📊 数据来源：公开市场数据</p>
    <p>⚠️ 本简报仅供参考，不构成投资建议</p>
    <p>投资有风险，决策需谨慎</p>
  </div>
</div>
</body>
</html>"""
    return html


def send_email(html_body, subject):
    """发送邮件"""
    msg = MIMEMultipart("alternative")
    msg["From"] = FROM_ADDR
    msg["To"] = TO_ADDR
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
    server.login(FROM_ADDR, PASSWORD)
    server.sendmail(FROM_ADDR, [TO_ADDR], msg.as_string())
    server.quit()
    print("✅ 邮件发送成功")


def main():
    today = date.today()
    weekday_idx = today.weekday()
    weekday = WEEKDAYS[weekday_idx]
    subject = f"A股日报 | {today} {weekday}"

    # 判断是否交易日（周末跳过）
    if weekday_idx >= 5:
        print(f"⏭️ 今日 {weekday}，非交易日，跳过")
        html = f"""<!DOCTYPE html><html><body style="font-family:'Microsoft YaHei';text-align:center;padding:40px;">
<h2>📈 A股日报</h2>
<p>{today} {weekday}</p>
<p style="color:#888;font-size:18px;">今日非交易日，下个交易日见 👋</p>
</body></html>"""
        send_email(html, subject)
        return

    print(f"📊 开始获取 {today} {weekday} 的市场数据...")

    # 获取指数行情
    print("→ 获取三大指数行情...")
    try:
        index_quotes = get_index_quotes()
        print(f"  上证: {index_quotes.get('sh000001', {}).get('price', '-')}")
        print(f"  深证: {index_quotes.get('sz399001', {}).get('price', '-')}")
        print(f"  创业板: {index_quotes.get('sz399006', {}).get('price', '-')}")
    except Exception as e:
        print(f"  ❌ 获取指数行情失败: {e}")
        index_quotes = {}

    # 获取市场涨跌分布
    print("→ 获取涨跌分布...")
    try:
        changedist = get_market_changedist()
        print(f"  上涨: {changedist.get('up')} 下跌: {changedist.get('down')}")
    except Exception as e:
        print(f"  ❌ 获取涨跌分布失败: {e}")
        changedist = {"up": "-", "down": "-", "flat": "-", "total": "-"}

    # 获取成交额
    print("→ 获取两市成交额...")
    try:
        amount = get_market_trade_data()
        print(f"  成交额: {amount}")
    except Exception as e:
        print(f"  ❌ 获取成交额失败: {e}")
        amount = "-"

    # 获取板块排行
    print("→ 获取板块排行...")
    try:
        sectors = get_sector_ranking()
        print(f"  板块数量: {len(sectors)}")
    except Exception as e:
        print(f"  ❌ 获取板块排行失败: {e}")
        sectors = []

    # 获取资讯
    print("→ 获取市场资讯...")
    try:
        news = get_market_news()
        print(f"  资讯数量: {len(news)}")
    except Exception as e:
        print(f"  ❌ 获取资讯失败: {e}")
        news = []

    # 生成 HTML
    print("→ 生成日报 HTML...")
    html = generate_html(index_quotes, changedist, amount, sectors, news)

    # 发送邮件
    print("→ 发送邮件...")
    try:
        send_email(html, subject)
    except Exception as e:
        print(f"  ❌ 发送邮件失败: {e}")
        raise

    print("🎉 日报任务完成！")


if __name__ == "__main__":
    main()
