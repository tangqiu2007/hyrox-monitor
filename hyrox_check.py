import os
import json
import requests
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo

# ===================== 配置常量 =====================
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASS = os.environ.get("SENDER_PASS")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
GIST_ID = os.environ.get("GIST_ID")
GIST_TOKEN = os.environ.get("GIST_TOKEN")

TARGET_URL = "https://china.hyrox.com/"
GIST_API_URL = f"https://api.github.com/gists/{GIST_ID}"
GIST_FILENAME = "hyrox_state.json"

# 监控配置
MONITOR = {
    "sanya_women_open": {
        "event_name": "三亚站 (2026.12.06)",
        "division": "Women Single Open"
    },
    "shanghai_doubles_mixed": {
        "event_name": "上海站 (2026.10.31)",
        "division": "Doubles Mixed"
    }
}
SANYA_DIVISIONS = [
    "Women Single Open",
    "Men Single Open",
    "Women Single Pro",
    "Men Single Pro",
    "Doubles Women",
    "Doubles Men",
    "Doubles Mixed",
    "Relay"
]
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
# ====================================================


def send_email(subject: str, body: str) -> bool:
    """发送邮件，内部捕获异常，返回是否发送成功"""
    if not all([SENDER_EMAIL, SENDER_PASS, RECEIVER_EMAIL]):
        print("❌ 邮件环境变量缺失")
        return False
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = Header(f"HYROX查票助手 <{SENDER_EMAIL}>")
        msg["To"] = Header(RECEIVER_EMAIL)
        msg["Subject"] = Header(subject, "utf-8")
        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=12)
        server.login(SENDER_EMAIL, SENDER_PASS)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        server.quit()
        print(f"✅邮件已发送: {subject}")
        return True
    except Exception as e:
        print(f"❌邮件发送异常: {e}")
        return False


def load_last_state() -> dict:
    """从Gist读取上一轮票态"""
    headers = {"Authorization": f"token {GIST_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        resp = requests.get(GIST_API_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        gist_data = resp.json()
        file_obj = gist_data["files"].get(GIST_FILENAME)
        if not file_obj:
            return {}
        return json.loads(file_obj["content"])
    except Exception as e:
        print(f"⚠️读取Gist状态失败:{e}")
        return {}


def save_current_state(state: dict):
    """把当前票态写入Gist"""
    headers = {"Authorization": f"token {GIST_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    payload = {
        "files": {
            GIST_FILENAME: {
                "content": json.dumps(state, ensure_ascii=False, indent=2)
            }
        }
    }
    try:
        requests.patch(GIST_API_URL, headers=headers, json=payload, timeout=15)
        print("✅已保存当前票态到Gist")
    except Exception as e:
        print(f"⚠️写入Gist状态失败:{e}")


def fetch_page_html() -> str:
    headers = {
        "User‑Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept‑Language": "zh‑CN,zh;q=0.9"
    }
    resp = requests.get(TARGET_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_event_availability(html: str):
    """
    返回:
        current_state: dict key为monitor key，value bool是否有票
        sanya_summary_text: str 三亚全组别文本报告
    """
    soup = BeautifulSoup(html, "html.parser")

    def is_division_available(event_text_block: str, division_name: str) -> bool:
        div_low = division_name.lower()
        if div_low not in event_text_block.lower():
            return False
        sold_tags = {"sold out", "soldout", "已售罄"}
        for tag in sold_tags:
            if tag in event_text_block.lower():
                return False
        return True

    # ---------- 三亚站文本块简易定位 ----------
    sanya_block = ""
    for section in soup.find_all("div"):
        sec_text = section.get_text(" ", strip=False)
        if "三亚" in sec_text or "sanya" in sec_text.lower():
            sanya_block = sec_text
            break

    # ---------- 上海站文本块简易定位 ----------
    shanghai_block = ""
    for section in soup.find_all("div"):
        sec_text = section.get_text(" ", strip=False)
        if ("上海" in sec_text or "shanghai" in sec_text.lower()) and ("10‑31" in sec_text or "oct 31" in sec_text.lower() or "10月31" in sec_text):
            shanghai_block = sec_text
            break

    current_state = {}
    current_state["sanya_women_open"] = is_division_available(sanya_block, MONITOR["sanya_women_open"]["division"])
    current_state["shanghai_doubles_mixed"] = is_division_available(shanghai_block, MONITOR["shanghai_doubles_mixed"]["division"])

    # 生成三亚站全组别汇总
    summary_lines = []
    for div_name in SANYA_DIVISIONS:
        avail = is_division_available(sanya_block, div_name)
        icon = "✅ 有票/可购买" if avail else "❌ 已售罄 (Sold Out)"
        summary_lines.append(f"• {div_name.ljust(22)} : {icon}")
    sanya_summary_text = "\n".join(summary_lines)
    return current_state, sanya_summary_text


def main():
    now_bj = datetime.now(TZ_SHANGHAI)
    print(f"[{now_bj.strftime('%Y‑%m‑%d %H:%M:%S')}] HYROX查票任务启动")
    try:
        html = fetch_page_html()
        current_state, sanya_summary = parse_event_availability(html)
        last_state = load_last_state()

        # -------- 判断哪些监控项发生【无票 → 有票】状态跃迁 --------
        trigger_alerts = []
        for k, cfg in MONITOR.items():
            prev = last_state.get(k, False)
            curr = current_state.get(k, False)
            if curr and not prev:
                trigger_alerts.append(f"🔥【{cfg['event_name']}】{cfg['division']} 出现余票！")

        # 有状态跃迁才发紧急告警
        if trigger_alerts:
            body = (
                f"检测时间：{now_bj.strftime('%Y‑%m‑%d %H:%M:%S')}\n\n"
                + "\n".join(trigger_alerts)
                + f"\n\n官网：{TARGET_URL}\n\n---三亚站全组别状态---\n{sanya_summary}"
            )
            send_email("🔥【余票紧急提醒】HYROX关注组别出现名额", body)

        # 保存本轮状态到Gist
        save_current_state(current_state)

        # ---------- 每日早/晚报发送窗口 ----------
        is_morning_report = (now_bj.hour == 9 and 0 <= now_bj.minute < 20)
        is_evening_report = (now_bj.hour == 18 and 0 <= now_bj.minute < 20)
        if is_morning_report or is_evening_report:
            rt = "早报" if is_morning_report else "晚报"
            body_lines = [
                f"HYROX查票助手 每日{rt} {now_bj.strftime('%m月%d日 %H:%M')}",
                "",
                "【重点监控组别】",
                f"• 三亚站 Women Single Open : {'✅有票' if current_state['sanya_women_open'] else '❌已售罄'}",
                f"• 上海站 Doubles Mixed     : {'✅有票' if current_state['shanghai_doubles_mixed'] else '❌已售罄'}",
                "",
                "【三亚站全组别状态】",
                sanya_summary,
                "",
                f"官方购票入口: {TARGET_URL}",
                "服务：每10分钟监控运行中。"
            ]
            send_email(f"📊【每日{rt}】HYROX赛事余票汇总", "\n".join(body_lines))

    except Exception as err:
        err_msg = f"HYROX脚本异常\n时间:{now_bj.strftime('%Y‑%m‑%d %H:%M:%S')}\n错误:{str(err)}"
        print(err_msg)
        try:
            send_email("⚠️【脚本运行异常警告】HYROX查票任务故障", err_msg)
        except Exception:
            pass


if __name__ == "__main__":
    main()
