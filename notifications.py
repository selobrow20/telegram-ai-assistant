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
    
    tot_exp = finance.format_rupiah(data['total_expense'])
    sisa_saldo = finance.format_rupiah(bal['balance'])
    
    if data['total_expense'] > 0:
        lines = [
            f"☀️ *Pagi, {user_name}!*",
            f"💸 *Kemarin kamu keluar:* `{tot_exp}` ({data['count']}x)",
        ]
        for c in data['categories'][:4]:
            lines.append(f"• {c['category']}: {finance.format_rupiah(c['total'])}")
            
        lines.append(f"💰 *Sisa Saldo:* `{sisa_saldo}`")
        return "\n".join(lines)
    else:
        return (
            f"☀️ *Pagi, {user_name}!*\n"
            f"✨ Kemarin kamu tidak ada pengeluaran (*Rp 0*).\n"
            f"💰 *Sisa Saldo:* `{sisa_saldo}`"
        )

def build_weekly_recap_message(user_id: int, user_name: str) -> str:
    data = db.get_last_7_days_expenses(user_id)
    bal = db.get_balance(user_id)
    
    tot_inc = finance.format_rupiah(data['total_income'])
    tot_exp = finance.format_rupiah(data['total_expense'])
    sisa = finance.format_rupiah(bal['balance'])
    
    lines = [
        "📅 *Rekap Mingguan*",
        f"• Masuk: `{tot_inc}`",
        f"• Keluar: `{tot_exp}`"
    ]
    
    if data['top_expense_categories']:
        top = ", ".join([f"{c['category']} ({finance.format_rupiah(c['total'])})" for c in data['top_expense_categories'][:3]])
        lines.append(f"• Pengeluaran: {top}")
        
    lines.append(f"💰 *Saldo:* `{sisa}`")
    return "\n".join(lines)

async def build_monthly_report_with_ai(user_id: int, user_name: str) -> Tuple[str, Optional[str]]:
    data = db.get_previous_month_summary(user_id)
    bal = db.get_balance(user_id)
    
    tot_inc = finance.format_rupiah(data['total_income'])
    tot_exp = finance.format_rupiah(data['total_expense'])
    sisa = finance.format_rupiah(bal['balance'])
    month_name = data['month_name']
    
    ai_analysis = ""
    if GEMINI_API_KEY and (data['total_income'] > 0 or data['total_expense'] > 0):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            cat_list = [f"{c['category']} {finance.format_rupiah(c['total'])}" for c in data['expense_categories'][:3]]
            cat_str = ", ".join(cat_list)
            prompt = (
                f"Tulis evaluasi keuangan singkat untuk {user_name} bulan {month_name}:\n"
                f"Masuk: {tot_inc}, Keluar: {tot_exp}, Sisa: {sisa}.\n"
                f"Kategori: {cat_str}.\n"
                f"PENTING: Tulis HANYA 2-3 kalimat ringkas (1 analisis pos boros + 1 saran praktis). Tanpa basa-basi pembuka/penutup."
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
        ai_analysis = "Pertahankan pencatatan harian dan usahakan menabung minimal 10-20% di awal bulan."
        
    lines = [
        f"📊 *Laporan Bulanan: {month_name}*",
        f"• Pemasukan: `{tot_inc}`",
        f"• Pengeluaran: `{tot_exp}`",
        f"• Saldo Kas: `{sisa}`\n",
        f"💡 *Catatan:* {ai_analysis}"
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
    
    return (
        f"⏰ *Laporan Tanggal {day}*\n"
        f"• Masuk Bulan Ini: `{tot_inc}`\n"
        f"• Keluar Bulan Ini: `{tot_exp}`\n"
        f"💰 *Saldo:* `{sisa}`"
    )

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
                text="🧪 Kirim Tes Notifikasi Sekarang",
                callback_data="test_notif_now"
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


async def send_test_notification(bot: Bot, user_id: int, chat_id: int, user_name: str):
    msg_text = build_daily_recap_message(user_id, user_name)
    test_header = (
        "🧪 *TES NOTIFIKASI BERHASIL*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Berikut adalah contoh format notifikasi rekap yang akan Anda terima otomatis:\n\n"
    )
    test_footer = (
        "\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ *Sistem notifikasi aktif & normal!*\n"
        "Jadwal pengiriman otomatis:\n"
        "• Daily Recap: Setiap hari 07:00 WIB\n"
        "• Weekly Recap: Setiap Senin 07:30 WIB\n"
        "• Monthly Report: Setiap tanggal 1 08:00 WIB\n"
        "• Scheduled Report: Setiap tanggal pilihan Anda 08:30 WIB"
    )
    await bot.send_message(chat_id=chat_id, text=test_header + msg_text + test_footer, parse_mode=ParseMode.MARKDOWN)


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
            
        await asyncio.sleep(25)
