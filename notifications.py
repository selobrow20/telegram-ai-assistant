import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

import database as db
import finance
from config import GEMINI_API_KEY
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# Timezone WIB (UTC+7)
WIB = timezone(timedelta(hours=7))

def get_now_wib() -> datetime:
    return datetime.now(WIB)

def format_date_id(date_str: str) -> str:
    # Mengubah YYYY-MM-DD menjadi DD/MM/YYYY
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return date_str

def build_daily_recap_message(user_id: int, user_name: str) -> str:
    data = db.get_yesterday_expenses(user_id)
    bal = db.get_balance(user_id)
    
    date_id = format_date_id(data['date'])
    tot_exp = finance.format_rupiah(data['total_expense'])
    sisa_saldo = finance.format_rupiah(bal['balance'])
    
    if data['total_expense'] > 0:
        lines = [
            f"☀️ *SELAMAT PAGI, {user_name.upper()}!* 👋",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"💸 *Rekap Pengeluaran Kemarin ({date_id}):*",
            f"Kemarin kamu keluar *{tot_exp}* ({data['count']} transaksi).\n",
            "📌 *Rincian per Kategori:*"
        ]
        for c in data['categories']:
            c_tot = finance.format_rupiah(c['total'])
            lines.append(f" • *{c['category']}*: {c_tot}")
            
        lines.append(f"\n💰 *Sisa Saldo Saat Ini:* `{sisa_saldo}`")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("_Semoga harimu menyenangkan dan tetap hemat hari ini!_ 😊")
        return "\n".join(lines)
    else:
        return (
            f"☀️ *SELAMAT PAGI, {user_name.upper()}!* 👋\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ Kemarin ({date_id}) kamu tidak mencatat pengeluaran sama sekali (*Rp 0*).\n"
            f"Keren & hemat banget! Pertahankan ya! 👏\n\n"
            f"💰 *Sisa Saldo Saat Ini:* `{sisa_saldo}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Siap menjalani hari ini dengan semangat baru!_ 🚀"
        )

def build_weekly_recap_message(user_id: int, user_name: str) -> str:
    data = db.get_last_7_days_expenses(user_id)
    bal = db.get_balance(user_id)
    
    start_id = format_date_id(data['start_date'])
    end_id = format_date_id(data['end_date'])
    
    tot_inc = finance.format_rupiah(data['total_income'])
    tot_exp = finance.format_rupiah(data['total_expense'])
    net = finance.format_rupiah(data['balance'])
    sisa = finance.format_rupiah(bal['balance'])
    
    lines = [
        "📅 *REKAP KEUANGAN MINGGUAN (SENIN CERIA)* ☀️",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"Halo *{user_name}*, berikut evaluasi keuanganmu selama 7 hari terakhir ({start_id} s/d {end_id}):\n",
        f"📥 *Total Pemasukan:* `{tot_inc}`",
        f"📤 *Total Pengeluaran:* `{tot_exp}`",
        f"💵 *Arus Kas Bersih:* `{net}`\n"
    ]
    
    if data['top_expense_categories']:
        lines.append("📌 *Pengeluaran Terbesar:*")
        for c in data['top_expense_categories'][:4]:
            c_tot = finance.format_rupiah(c['total'])
            lines.append(f" • *{c['category']}*: {c_tot} ({c['count']}x)")
            
    lines.append(f"\n💰 *Total Saldo Sekarang:* `{sisa}`")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_Yuk mulai minggu baru ini dengan rencana keuangan yang rapi dan terkontrol!_ 💪")
    return "\n".join(lines)

async def build_monthly_report_with_ai(user_id: int, user_name: str) -> Tuple[str, Optional[str]]:
    data = db.get_previous_month_summary(user_id)
    bal = db.get_balance(user_id)
    
    tot_inc = finance.format_rupiah(data['total_income'])
    tot_exp = finance.format_rupiah(data['total_expense'])
    net = finance.format_rupiah(data['balance'])
    sisa = finance.format_rupiah(bal['balance'])
    month_name = data['month_name']
    
    # Generate analisis AI melalui Gemini
    ai_analysis = ""
    if GEMINI_API_KEY and (data['total_income'] > 0 or data['total_expense'] > 0):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = (
                f"Anda adalah konsultan keuangan pribadi 'Selobrow'.\n"
                f"Analisis keuangan pengguna bernama {user_name} untuk bulan {month_name}:\n"
                f"- Total Pemasukan: {tot_inc}\n"
                f"- Total Pengeluaran: {tot_exp}\n"
                f"- Arus Kas Bersih: {net}\n"
                f"- Kategori Pengeluaran: {', '.join([f'{c["category"]} ({finance.format_rupiah(c["total"])})' for c in data['expense_categories'][:5]])}\n"
                f"- Sisa Saldo Total: {sisa}\n\n"
                f"Berikan:\n"
                f"1. Analisis kesehatan finansial singkat (2-3 kalimat santai dan ramah).\n"
                f"2. Evaluasi kategori yang paling boros / prioritas.\n"
                f"3. 2 tips praktis dan actionable untuk bulan berikutnya.\n"
                f"Gunakan gaya bahasa Indonesia yang suportif, hangat, dan bersahabat dengan emoji yang pas."
            )
            resp = client.models.generate_content(
                model="gemini-3.1-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.7)
            )
            ai_analysis = resp.text.strip() if resp.text else ""
        except Exception as e:
            logger.warning(f"Gagal generate analisis AI bulanan: {e}")
            
    if not ai_analysis:
        ai_analysis = (
            "💡 *Saran Finansial:*\n"
            "Terus pantau arus kas Anda setiap hari. Usahakan menyisihkan minimal 20% dari setiap pemasukan untuk tabungan atau dana darurat sebelum dibelanjakan!"
        )
        
    lines = [
        f"📊 *LAPORAN BULANAN RESMI: {month_name.upper()}*",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"Halo *{user_name}*, berikut rekapitulasi keuangan Anda bulan lalu:\n",
        f"📥 *Total Pemasukan:* `{tot_inc}`",
        f"📤 *Total Pengeluaran:* `{tot_exp}`",
        f"💵 *Arus Kas Bersih:* `{net}`",
        f"💰 *Saldo Tersisa:* `{sisa}`\n",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "🧠 *ANALISIS & SARAN SELOBROW:*",
        ai_analysis,
        "━━━━━━━━━━━━━━━━━━━━━━",
        "_File rekapitulasi Excel (.xlsx) bulan ini telah dilampirkan di bawah._"
    ]
    
    excel_path = None
    try:
        excel_path = finance.export_financial_report_excel(user_id, "all")
    except Exception as ee:
        logger.warning(f"Gagal generate Excel bulanan: {ee}")
        
    return "\n".join(lines), excel_path

def build_scheduled_report_message(user_id: int, user_name: str, day: int) -> str:
    summary = db.get_category_breakdown(user_id, "month")
    bal = db.get_balance(user_id)
    
    tot_inc = finance.format_rupiah(summary['total_income'])
    tot_exp = finance.format_rupiah(summary['total_expense'])
    sisa = finance.format_rupiah(bal['balance'])
    
    lines = [
        f"⏰ *LAPORAN TERJADWAL (TANGGAL {day})* 🔔",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"Halo *{user_name}*, ini pengingat keuangan otomatis Anda per tanggal {day}:\n",
        f"💰 *Saldo Saat Ini:* `{sisa}`",
        f"📥 *Pemasukan Bulan Ini:* `{tot_inc}`",
        f"📤 *Pengeluaran Bulan Ini:* `{tot_exp}`\n"
    ]
    
    if summary['expense_categories']:
        lines.append("📌 *Pengeluaran Terbesar Bulan Ini:*")
        for c in summary['expense_categories'][:3]:
            lines.append(f" • *{c['category']}*: {finance.format_rupiah(c['total'])}")
            
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_Ketik /excel untuk mengunduh laporan spreadsheet Excel kapan saja._")
    return "\n".join(lines)

def get_notification_settings_keyboard(settings: Dict[str, Any]) -> InlineKeyboardMarkup:
    daily_icon = "✅ Aktif" if settings.get('daily_recap_enabled') else "❌ Nonaktif"
    weekly_icon = "✅ Aktif" if settings.get('weekly_recap_enabled') else "❌ Nonaktif"
    monthly_icon = "✅ Aktif" if settings.get('monthly_report_enabled') else "❌ Nonaktif"
    sched_icon = "✅ Aktif" if settings.get('scheduled_reports_enabled') else "❌ Nonaktif"
    sched_day = settings.get('scheduled_day', 25)
    
    keyboard = [
        [
            InlineKeyboardButton(
                text=f"☀️ Rekap Harian (07:00): {daily_icon}",
                callback_data="toggle_notif_daily"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"📅 Rekap Mingguan (Senin): {weekly_icon}",
                callback_data="toggle_notif_weekly"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"📑 Laporan Bulanan + AI: {monthly_icon}",
                callback_data="toggle_notif_monthly"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"⏰ Laporan Terjadwal: {sched_icon}",
                callback_data="toggle_notif_scheduled"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🗓️ Ubah Tanggal Terjadwal (Saat Ini: Tgl {sched_day})",
                callback_data="menu_change_sched_day"
            )
        ],
        [
            InlineKeyboardButton(
                text="🔙 Kembali ke Menu Utama",
                callback_data="menu_help"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def start_notification_scheduler(bot: Bot):
    logger.info("Background Notification Scheduler dimulai (Timezone: Asia/Jakarta WIB).")
    
    while True:
        try:
            now = get_now_wib()
            today_str = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M")
            day_num = now.day
            weekday_num = now.weekday()  # 0 = Senin
            month_str = now.strftime("%Y-%m")
            
            subscribers = db.get_all_active_users_for_notification()
            
            for user in subscribers:
                user_id = user['user_id']
                chat_id = user.get('chat_id') or user_id
                user_name = user.get('user_name') or 'Teman'
                
                # 1. Daily Recap (Setiap pagi jam 07:00 atau waktu kustom)
                daily_time = user.get('daily_recap_time') or '07:00'
                if user.get('daily_recap_enabled') and time_str == daily_time:
                    if user.get('last_daily_sent') != today_str:
                        try:
                            msg_text = build_daily_recap_message(user_id, user_name)
                            await bot.send_message(chat_id=chat_id, text=msg_text, parse_mode=ParseMode.MARKDOWN)
                            db.update_notification_setting(user_id, 'last_daily_sent', today_str)
                            logger.info(f"Daily recap terkirim ke user {user_id}")
                        except Exception as de:
                            logger.warning(f"Gagal kirim daily recap ke {user_id}: {de}")
                            
                # 2. Weekly Recap (Setiap Senin pagi jam 07:30)
                if user.get('weekly_recap_enabled') and weekday_num == 0 and time_str == "07:30":
                    if user.get('last_weekly_sent') != today_str:
                        try:
                            msg_text = build_weekly_recap_message(user_id, user_name)
                            await bot.send_message(chat_id=chat_id, text=msg_text, parse_mode=ParseMode.MARKDOWN)
                            db.update_notification_setting(user_id, 'last_weekly_sent', today_str)
                            logger.info(f"Weekly recap terkirim ke user {user_id}")
                        except Exception as we:
                            logger.warning(f"Gagal kirim weekly recap ke {user_id}: {we}")
                            
                # 3. Monthly Report + Analisis AI (Setiap tanggal 1 jam 08:00)
                if user.get('monthly_report_enabled') and day_num == 1 and time_str == "08:00":
                    if user.get('last_monthly_sent') != month_str:
                        try:
                            msg_text, excel_path = await build_monthly_report_with_ai(user_id, user_name)
                            await bot.send_message(chat_id=chat_id, text=msg_text, parse_mode=ParseMode.MARKDOWN)
                            if excel_path:
                                await bot.send_document(
                                    chat_id=chat_id,
                                    document=FSInputFile(excel_path),
                                    caption=f"📊 File Laporan Keuangan Bulanan ({month_str})"
                                )
                            db.update_notification_setting(user_id, 'last_monthly_sent', month_str)
                            logger.info(f"Monthly report terkirim ke user {user_id}")
                        except Exception as me:
                            logger.warning(f"Gagal kirim monthly report ke {user_id}: {me}")
                            
                # 4. Scheduled Reports (Setiap tanggal tertentu pilihan pengguna jam 08:30)
                sched_day = user.get('scheduled_day') or 25
                if user.get('scheduled_reports_enabled') and day_num == sched_day and time_str == "08:30":
                    if user.get('last_scheduled_sent') != today_str:
                        try:
                            msg_text = build_scheduled_report_message(user_id, user_name, sched_day)
                            await bot.send_message(chat_id=chat_id, text=msg_text, parse_mode=ParseMode.MARKDOWN)
                            db.update_notification_setting(user_id, 'last_scheduled_sent', today_str)
                            logger.info(f"Scheduled report terkirim ke user {user_id}")
                        except Exception as se:
                            logger.warning(f"Gagal kirim scheduled report ke {user_id}: {se}")

        except Exception as loop_err:
            logger.error(f"Error pada notification scheduler loop: {loop_err}", exc_info=True)
            
        await asyncio.sleep(60)
