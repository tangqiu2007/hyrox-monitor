# 2. 每日早/晚报：每天北京时间 09:00-09:20 及 17:00-17:20 各发送一次全量汇总
        if (now_bj.hour == 9 and now_bj.minute < 20) or (now_bj.hour == 17 and now_bj.minute < 20):
            report_type = "早报" if now_bj.hour == 9 else "晚报"
            send_email(
                f"📊【每日{report_type}】HYROX 赛事余票汇总 ({now_bj.strftime('%m月%d日 %H:%M')})",
                f"您好！HYROX 查票助手为您送上最新票源状态{report_type}：\n\n"
                f"【重点监控组别】\n"
                f"• 三亚站 (2026.12.06) Women Single Open : {'✅ 有票' if sanya_has_ticket else '❌ 已售罄'}\n"
                f"• 10.31 站 Doubles Mixed               : {'✅ 有票' if oct31_has_ticket else '❌ 已售罄'}\n\n"
                f"【三亚站 (2026.12.06) 全组别状态】\n"
                f"{sanya_summary}\n\n"
                f"官方购票入口：{TARGET_URL}\n"
                f"服务状态：每 10 分钟自动监控运行中。"
            )
