import os
import re
import requests
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header

# 从 GitHub Actions Secrets 中读取敏感配置
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASS = os.environ.get("SENDER_PASS")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

TARGET_URL = "https://china.hyrox.com/"

def send_email(subject, body):
    """通过 SSL 发送邮件通知"""
    if not SENDER_EMAIL or not SENDER_PASS or not RECEIVER_EMAIL:
        print("❌ 错误：未读取到环境变量 secrets，请检查 GitHub Settings 配置！")
        return

    try:
        message = MIMEText(body, 'plain', 'utf-8')
        message['From'] = Header(f"HYROX 查票助手 <{SENDER_EMAIL}>")
        message['To'] = Header(RECEIVER_EMAIL)
        message['Subject'] = Header(subject, 'utf-8')

        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=10)
        server.login(SENDER_EMAIL, SENDER_PASS)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], message.as_string())
        server.quit()
        print(f"[{datetime.now()}] ✅ 邮件成功发送：{subject}")
    except Exception as e:
        print(f"[{datetime.now()}] ❌ 邮件发送异常: {e}")

def fetch_hyrox_status():
    """
    抓取 china.hyrox.com 页面并判断各大赛事及组别票源状态
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }

    res = requests.get(TARGET_URL, headers=headers, timeout=20)
    res.raise_for_status() # 页面非 200 时触发异常报警
    html_text = res.text

    # 1. 检测目标一：三亚站 (2026.12.06) Women Single Open
    sanya_women_open_has_ticket = False
    sanya_pattern = re.compile(rf"(三亚|Sanya).*?Women Single Open.*?(sold\s*out|已售罄|soldout)", re.IGNORECASE | re.DOTALL)
    # 通用与精准匹配结合
    if "Women Single Open" in html_text and not sanya_pattern.search(html_text):
        sanya_women_open_has_ticket = True

    # 2. 检测目标二：上海站 (2026.10.31) Doubles Mixed (双人混双)
    shanghai_doubles_mixed_has_ticket = False
    shanghai_pattern = re.compile(rf"(上海|Shanghai).*?(2026-10-31|10月31日|Oct 31)?.*?Doubles Mixed.*?(sold\s*out|已售罄|soldout)", re.IGNORECASE | re.DOTALL)
    
    # 只要页面中包含上海站或 10.31 的 Doubles Mixed 且无售罄标识
    if ("Shanghai" in html_text or "上海" in html_text or "10-31" in html_text) and "Doubles Mixed" in html_text:
        if not shanghai_pattern.search(html_text):
            shanghai_doubles_mixed_has_ticket = True

    # 生成三亚站全组别概览（用于早晚报）
    divisions = [
        "Women Single Open",
        "Men Single Open",
        "Women Single Pro",
        "Men Single Pro",
        "Doubles Women",
        "Doubles Men",
        "Doubles Mixed",
        "Relay"
    ]
    summary_list = []
    for div in divisions:
        p = re.compile(rf"{div}.*?(sold\s*out|已售罄|soldout)", re.IGNORECASE | re.DOTALL)
        is_avail = (div in html_text) and (not p.search(html_text))
        status_icon = "✅ 有票/可购买" if is_avail else "❌ 已售罄 (Sold Out)"
        summary_list.append(f"• {div.ljust(20)} : {status_icon}")

    summary_text = "\n".join(summary_list)

    return sanya_women_open_has_ticket, shanghai_doubles_mixed_has_ticket, summary_text

if __name__ == "__main__":
    beijing_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(beijing_tz)

    print(f"[{now_bj.strftime('%Y-%m-%d %H:%M:%S')}] 开始执行 HYROX 票源检测...")

    try:
        sanya_has_ticket, shanghai_has_ticket, sanya_summary = fetch_hyrox_status()

        # 1. 紧急发信触发（重点组别出现余票）
        alerts = []
        if sanya_has_ticket:
            alerts.append("【三亚站 (2026.12.06) Women Single Open】出现余票！")
        if shanghai_has_ticket:
            alerts.append("【上海站 (2026.10.31) Doubles Mixed (双人混双)】出现余票！")

        if alerts:
            alert_body = "\n".join([f"🔥 {item}" for item in alerts])
            send_email(
                "🔥【余票紧急提醒】HYROX 关注组别出现可用名额！",
                f"检测时间：{now_bj.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"检测到以下你关注的组别已放票：\n"
                f"{alert_body}\n\n"
                f"请立即前往官网抢票：{TARGET_URL}\n\n"
                f"--- 三亚站全组别实时状态 ---\n{sanya_summary}"
            )

        # 2. 每日早/晚报：每天北京时间 09:00-09:20 及 17:00-17:20 各发送一次全量汇总
        if (now_bj.hour == 9 and now_bj.minute < 20) or (now_bj.hour == 17 and now_bj.minute < 20):
            report_type = "早报" if now_bj.hour == 9 else "晚报"
            send_email(
                f"📊【每日{report_type}】HYROX 赛事余票汇总 ({now_bj.strftime('%m月%d日 %H:%M')})",
                f"您好！HYROX 查票助手为您送上最新票源状态{report_type}：\n\n"
                f"【重点监控组别】\n"
                f"• 三亚站 (2026.12.06) Women Single Open : {'✅ 有票' if sanya_has_ticket else '❌ 已售罄'}\n"
                f"• 上海站 (2026.10.31) Doubles Mixed     : {'✅ 有票' if shanghai_has_ticket else '❌ 已售罄'}\n\n"
                f"【三亚站 (2026.12.06) 全组别状态】\n"
                f"{sanya_summary}\n\n"
                f"官方购票入口：{TARGET_URL}\n"
                f"服务状态：每 10 分钟自动监控运行中。"
            )

    except Exception as e:
        send_email(
            "⚠️【脚本运行异常警告】HYROX 查票任务故障",
            f"报告：HYROX 查票脚本在执行过程中抛出异常！\n\n"
            f"故障时间：{now_bj.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"错误详情：{str(e)}"
        )
