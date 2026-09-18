import os
import json
import requests
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
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
        "city_keyword": "三亚",
        "event_name": "三亚站 (2026.12.06)",
        "division": "Women Single Open"
    },
    "shanghai_doubles_mixed": {
        "city_keyword": "上海",
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
        # 使用 formataddr 规范发件人 Header，解决部分 SMTP 网关退信问题
        msg["From"] = formataddr(("HYROX查票助手", SENDER_EMAIL))
        msg["To"] = Header(RECEIVER_EMAIL)
        msg["Subject"] = Header(subject, "utf-8")

        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=12)
        server.login(SENDER_EMAIL, SENDER_PASS)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
        server.quit()
        print(f"✅ 邮件已发送: {subject}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送异常: {e}")
        return False


def load_last_state() -> dict | None:
    """从 Gist 读取上一轮票态，失败时返回 None 避免误判跃迁"""
    if not GIST_ID or not GIST_TOKEN:
        print("⚠️ GIST_ID 或 GIST_TOKEN 未配置")
        return None
    headers = {
        "Authorization": f"token {GIST_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        resp = requests.get(GIST_API_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        gist_data = resp.json()
        file_obj = gist_data.get("files", {}).get(GIST_FILENAME)
        if not file_obj:
            return {}
        return json.loads(file_obj["content"])
    except Exception as e:
        print(f"⚠️ 读取 Gist 状态失败: {e}")
        return None


def save_current_state(state: dict):
    """把当前票态写入 Gist"""
    if not GIST_ID or not GIST_TOKEN:
        print("⚠️ GIST 未配置，跳过状态保存")
        return
    headers = {
        "Authorization": f"token {GIST_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "files": {
            GIST_FILENAME: {
                "content": json.dumps(state, ensure_ascii=False, indent=2)
            }
        }
    }
    try:
        resp = requests.patch(GIST_API_URL, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        print("✅ 已保存当前票态到 Gist")
    except Exception as e:
        print(f"⚠️ 写入 Gist 状态失败: {e}")


def fetch_page_html() -> str:
    """获取目标页面 HTML（使用标准 ASCII 请求头）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9"
    }
    resp = requests.get(TARGET_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text


def is_division_available(soup: BeautifulSoup, city_keyword: str, division_name: str) -> bool:
    """
    精确定位具体城市和组别的最小 DOM 卡片，判断该组别是否有票。
    避免全页查找导致单组别售罄误判全局。
    """
    city_kw = city_keyword.lower()
    div_kw = division_name.lower()
    sold_tags = ["sold out", "soldout", "已售罄", "暂无名额"]

    candidate_tags = soup.find_all(["div", "section", "article", "tr", "li"])

    # 查找同时包含城市关键字与组别关键字的 DOM 节点
    matching_nodes = []
    for tag in candidate_tags:
        text = tag.get_text(" ", strip=True).lower()
        if city_kw in text and div_kw in text:
            matching_nodes.append((len(text), text))

    if matching_nodes:
        # 取范围最小的节点（文本长度最短），精准聚焦单个卡片
        matching_nodes.sort(key=lambda x: x[0])
        smallest_text = matching_nodes[0][1]
        for tag in sold_tags:
            if tag in smallest_text:
                return False
        return True

    # 兜底：若未找到包含城市的复合节点，尝试匹配独立的组别卡片
    for tag in candidate_tags:
        text = tag.get_text(" ", strip=True).lower()
        if div_kw in text and len(text) < 500:
            for tag in sold_tags:
                if tag in text:
                    return False
            return True

    return False


def parse_event_availability(html: str):
    """
    解析网页，返回：
        current_state: dict，包含监控项是否有票
        sanya_summary_text: str，三亚站全组别汇总状态
    """
    soup = BeautifulSoup(html, "html.parser")

    current_state = {}
    for key, cfg in MONITOR.items():
        current_state[key] = is_division_available(
            soup,
            cfg["city_keyword"],
            cfg["division"]
        )

    # 生成三亚站全组别汇总
    summary_lines = []
    for div_name in SANYA_DIVISIONS:
        avail = is_division_available(soup, "三亚", div_name)
        icon = "✅ 有票/可购买" if avail else "❌ 已售罄 (Sold Out)"
        summary_lines.append(f"• {div_name.ljust(22)} : {icon}")

    sanya_summary_text = "\n".join(summary_lines)
    return current_state, sanya_summary_text


def main():
    now_bj = datetime.now(TZ_SHANGHAI)
    print(f"[{now_bj.strftime('%Y-%m-%d %H:%M:%S')}] HYROX 查票任务启动")

    try:
        html = fetch_page_html()
        current_state, sanya_summary = parse_event_availability(html)
        last_state = load_last_state()

        # -------- 判断哪些监控项发生【无票 → 有票】状态跃迁 --------
        trigger_alerts = []
        if last_state is not None:
            for k, cfg in MONITOR.items():
                prev = last_state.get(k, False)
                curr = current_state.get(k, False)
                if curr and not prev:
                    trigger_alerts.append(f"🔥【{cfg['event_name']}】{cfg['division']} 出现余票！")
        else:
            print("ℹ️ 未能获取上一轮状态，本次跳过跃迁告警判定")

        # 存在状态跃迁才发送紧急提醒
        if trigger_alerts:
            body = (
                f"检测时间：{now_bj.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                + "\n".join(trigger_alerts)
                + f"\n\n官网：{TARGET_URL}\n\n---三亚站全组别状态---\n{sanya_summary}"
            )
            send_email("🔥【余票紧急提醒】HYROX 关注组别出现名额", body)

        # ---------- 自动补发每日早/晚报逻辑（记录日期到 Gist，彻底解决 Actions 延迟漏发问题） ----------
        today_str = now_bj.strftime("%Y-%m-%d")
        last_morning_date = last_state.get("last_morning_date") if last_state else None
        last_evening_date = last_state.get("last_evening_date") if last_state else None

        # 只要过了上午 09:00 且今天还没发过早报，就触发
        is_morning_report = (now_bj.hour >= 9) and (last_morning_date != today_str)
        # 只要过了下午 18:00 且今天还没发过晚报，就触发
        is_evening_report = (now_bj.hour >= 18) and (last_evening_date != today_str)

        if is_morning_report or is_evening_report:
            rt = "早报" if is_morning_report else "晚报"
            body_lines = [
                f"HYROX 查票助手 每日{rt} {now_bj.strftime('%m月%d日 %H:%M')}",
                "",
                "【重点监控组别】",
                f"• 三亚站 Women Single Open : {'✅有票' if current_state.get('sanya_women_open') else '❌已售罄'}",
                f"• 上海站 Doubles Mixed     : {'✅有票' if current_state.get('shanghai_doubles_mixed') else '❌已售罄'}",
                "",
                "【三亚站全组别状态】",
                sanya_summary,
                "",
                f"官方购票入口: {TARGET_URL}",
                "服务：监控自动运行中。"
            ]
            if send_email(f"📊【每日{rt}】HYROX 赛事余票汇总", "\n".join(body_lines)):
                if is_morning_report:
                    current_state["last_morning_date"] = today_str
                if is_evening_report:
                    current_state["last_evening_date"] = today_str

        # 保持历史发报记录（如果本次没有触发发报，继承上一轮记录）
        if last_state:
            if "last_morning_date" in last_state and "last_morning_date" not in current_state:
                current_state["last_morning_date"] = last_state["last_morning_date"]
            if "last_evening_date" in last_state and "last_evening_date" not in current_state:
                current_state["last_evening_date"] = last_state["last_evening_date"]

        # 保存本轮状态及早晚报发送记录到 Gist
        save_current_state(current_state)

    except Exception as err:
        err_msg = f"HYROX 脚本异常\n时间:{now_bj.strftime('%Y-%m-%d %H:%M:%S')}\n错误:{str(err)}"
        print(err_msg)
        try:
            send_email("⚠️【脚本运行异常警告】HYROX 查票任务故障", err_msg)
        except Exception:
            pass


if __name__ == "__main__":
    main()
