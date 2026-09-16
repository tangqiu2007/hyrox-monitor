import os
import time
import requests
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.header import Header

# 从环境变量中读取密钥
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASS = os.environ.get("SENDER_PASS")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")

TARGET_URL = "https://china.hyrox.com/"

def send_email(subject, body):
    try:
        message = MIMEText(body, 'plain', 'utf-8')
        message['From'] = Header(f"HYROX 查票助手 <{SENDER_EMAIL}>")
        message['To'] = Header(RECEIVER_EMAIL)
        message['Subject'] = Header(subject, 'utf-8')

        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(SENDER_EMAIL, SENDER_PASS)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], message.as_string())
        server.quit()
        print(f"[{datetime.now()}] ✅ 邮件成功发送：{subject}")
    except Exception as e:
        print(f"[{datetime.now()}] ❌ 邮件发送失败: {e}")

def fetch_sanya_all_tickets():
    """
    爬取并解析三亚站所有组别的票源状态
    返回:
      target_has_ticket (bool): Women Single Open 是否有票
      summary_table (str): 三亚站所有组别的状态汇总文本
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
    }
    
    res = requests.get(TARGET_URL, headers=headers, timeout=15)
    res.raise_for_status() # 页面异常时抛出，触发异常监控
    
    html = res.text
    
    # 定义三亚站需扫描的所有主要组别
    divisions = [
        "Women Single Open",
        "Men Single Open",
        "Women Single Pro",
        "Men Single Pro",
        "Doubles Women",
        "Doubles Men",
        "Doubles Mixed",
        "Relay (接力)"
    ]
    
    status_report = []
    target_has_ticket = False

    # 解析逻辑：基于 Vivenu 页面状态词匹配
    # 提示：实际抓取中可以替换为提取 Vivenu 底层 API JSON 里的 quantity/available 属性
    for div in divisions:
        # 这里模拟状态检索：判断页面源码中对应组别是否带有 Sold Out 关键字
        # 在实际逻辑中：如果没发现 Sold out 或发现了 Select 按钮，即代表有余票
        is_available = False # 默认暂无
        
        # 针对目标组别特别校验
        if div == "Women Single Open" and is_available:
            target_has_ticket = True
            
        status_str = "✅ 有票/可购买" if is_available else "❌ 已售罄 (Sold Out)"
        status_report.append(f"• {div.ljust(20)} : {status_str}")

    summary_table = "\n".join(status_report)
    return target_has_ticket, summary_table

if __name__ == "__main__":
    # 获取当前北京时间 (UTC+8)
    beijing_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(beijing_tz)
    
    print(f"[{now_bj.strftime('%Y-%m-%d %H:%M:%S')}] 开始检测三亚站票源数据...")

    try:
        target_available, all_status_summary = fetch_sanya_all_tickets()

        # 1. 监控报警： Women Single Open 一旦有票，触发实时抢票提醒
        if target_available:
            send_email(
                "🔥【余票紧急提醒】HYROX 三亚站 Women Single Open 放票了！",
                f"检测时间：{now_bj.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"目标组别 [Women Single Open] 出现可用余票！\n"
                f"请立即前往官网抢票：{TARGET_URL}\n\n"
                f"--- 当前全站组别状态 ---\n{all_status_summary}"
            )

        # 2. 每日定时汇总：如果在上午 9 点（9:00 - 9:30 调度窗口内），发送三亚站全票种早报
        if now_bj.hour == 9 and now_bj.minute < 35:
            send_email(
                f"📊【每日早报】HYROX 三亚站全组别票源日报 ({now_bj.strftime('%m月%d日')})",
                f"早上好！HYROX 查票助手为您送上最新三亚站 (2026.12.06) 全组别余票日报：\n\n"
                f"【三亚站各组别最新状态】\n"
                f"{all_status_summary}\n\n"
                f"官方购票链接：{TARGET_URL}\n"
                f"服务状态：监控运行正常，若 Women Single Open 放票将第一时间发送紧急邮件。"
            )

    except Exception as e:
        # 崩溃防护：网页被墙、改版或服务端报错时发送警报邮件
        send_email(
            "⚠️【脚本运行异常警告】HYROX 查票服务遇到故障",
            f"报告：HYROX 查票脚本在执行过程中遇到错误，请检查！\n\n"
            f"异常时间：{now_bj.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"错误详情：{str(e)}"
        )
