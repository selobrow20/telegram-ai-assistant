import asyncio
import io
import logging
import os
import sys
from pathlib import Path
import re

from typing import Callable, Dict, Any, Awaitable
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    TelegramObject
)

from config import TELEGRAM_BOT_TOKEN, VOICE_REPLY_ENABLED, ADMIN_USER_ID
import database as db
import finance
import gemini_agent
import tts
import pdf_converter
import notifications
import pricelist


# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("TelegramAIAssistant")

if not TELEGRAM_BOT_TOKEN:
    logger.warning("Peringatan: TELEGRAM_BOT_TOKEN belum diset di .env. Pastikan mengisinya sebelum menjalankan bot.")

# Inisialisasi Dispatcher
dp = Dispatcher()

class AccessControlMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        user_id = user.id
        user_name = user.first_name or "Teman"
        username = user.username or ""

        # Jika callback adalah persetujuan/penolakan akses oleh owner, jangan cegat!
        if isinstance(event, CallbackQuery):
            if event.data and (event.data.startswith("auth_approve_") or event.data.startswith("auth_reject_")):
                return await handler(event, data)

        # Cek apakah user sudah terotorisasi (Owner / Approved)
        if db.is_user_authorized(user_id, ADMIN_USER_ID):
            chat_id = event.chat.id if isinstance(event, Message) else (event.message.chat.id if event.message else user_id)
            db.register_or_update_user(user_id, user_name, chat_id)
            return await handler(event, data)

        # Jika belum, daftarkan atau periksa status permohonan
        chat_id = event.chat.id if isinstance(event, Message) else (event.message.chat.id if event.message else user_id)
        status, is_new = db.request_access(user_id, user_name, username, chat_id, ADMIN_USER_ID)

        if status == "approved":
            # Otomatis disetujui (misal user pertama otomatis menjadi Owner)
            db.register_or_update_user(user_id, user_name, chat_id)
            return await handler(event, data)

        bot: Bot = data["bot"]

        if status == "pending":
            msg_text = (
                "🔒 *Akses Terbatas (Akun Belum Terverifikasi)*\n\n"
                "Bot ini bersifat privat. Permintaan akses Anda telah dikirimkan ke pemilik bot untuk diverifikasi.\n\n"
                f"🆔 *User ID Anda:* `{user_id}`\n\n"
                "Silakan tunggu hingga pemilik bot menyetujui akses Anda."
            )
            if isinstance(event, Message):
                await event.answer(msg_text, parse_mode=ParseMode.MARKDOWN)
            elif isinstance(event, CallbackQuery):
                await event.answer("Akses Anda belum diverifikasi oleh pemilik bot.", show_alert=True)

            # Jika ini permintaan baru pertama kali, kirim notifikasi ke Owner!
            if is_new:
                owners = db.get_owners()
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(text="✅ Izinkan Akses", callback_data=f"auth_approve_{user_id}"),
                            InlineKeyboardButton(text="❌ Tolak", callback_data=f"auth_reject_{user_id}")
                        ]
                    ]
                )
                uname_str = f"@{username}" if username else "-"
                notify_text = (
                    "🔔 *PERMINTAAN VERIFIKASI PENGGUNA BARU*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 *Nama:* {user_name}\n"
                    f"🔗 *Username:* {uname_str}\n"
                    f"🆔 *User ID:* `{user_id}`\n\n"
                    "Ada yang ingin menggunakan bot Anda. Apakah Anda ingin mengizinkan akses orang ini?"
                )
                for owner in owners:
                    try:
                        await bot.send_message(owner["chat_id"], notify_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
                    except Exception as e:
                        logger.warning(f"Gagal mengirim notif izin ke owner {owner['user_id']}: {e}")

                if ADMIN_USER_ID and str(ADMIN_USER_ID).isdigit():
                    adm_int = int(ADMIN_USER_ID)
                    if not any(o["user_id"] == adm_int for o in owners):
                        try:
                            await bot.send_message(adm_int, notify_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
                        except Exception:
                            pass
            return  # Hentikan proses, jangan teruskan ke command/handler

        elif status == "rejected":
            reject_msg = "❌ Maaf, akses Anda untuk menggunakan bot ini telah ditolak oleh pemilik."
            if isinstance(event, Message):
                await event.answer(reject_msg)
            elif isinstance(event, CallbackQuery):
                await event.answer("Akses Anda ditolak oleh pemilik.", show_alert=True)
            return

def get_main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🏷️ Cek Harga (ADP)", callback_data="menu_harga"),
            InlineKeyboardButton(text="💰 Cek Saldo", callback_data="menu_saldo")
        ],
        [
            InlineKeyboardButton(text="📑 Laporan Bulan Ini", callback_data="menu_lap_month"),
            InlineKeyboardButton(text="📅 Laporan Hari Ini", callback_data="menu_lap_today")
        ],
        [
            InlineKeyboardButton(text="⏳ Laporan 7 Hari", callback_data="menu_lap_week"),
            InlineKeyboardButton(text="📥 Download Excel", callback_data="menu_excel")
        ],
        [
            InlineKeyboardButton(text="✅ Daftar To-Do", callback_data="menu_tasks"),
            InlineKeyboardButton(text="📝 Catatan Harian", callback_data="menu_notes")
        ],
        [
            InlineKeyboardButton(text="📅 Kalender & Agenda", callback_data="menu_kalender"),
            InlineKeyboardButton(text="⏰ Alarm & Pengingat", callback_data="menu_pengingat")
        ],
        [
            InlineKeyboardButton(text="🔔 Notifikasi Cerdas", callback_data="menu_notifikasi"),
            InlineKeyboardButton(text="🗑️ Reset Saldo", callback_data="menu_resetsaldo")
        ],
        [
            InlineKeyboardButton(text="💡 Bantuan", callback_data="menu_help")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@dp.message(Command("reset"))
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    gemini_agent.clear_user_history(user_id)
    user_name = message.from_user.first_name if message.from_user else "Teman"
    db.register_or_update_user(user_id, user_name, message.chat.id)
    welcome_text = (
        f"👋 Yo *{user_name}*!\n\n"
        "Gue **Selobrow**, asisten pribadi lu yang siap bantu kapan aja. Santai aja bor, lu bisa kirim teks atau Voice Note buat:\n"
        "• 🏷️ *Cek Harga Pricelist* (langsung ketik tipe/model produk)\n"
        "• 💸 *Catat Duit & Pantau Saldo*\n"
        "• 📊 *Laporan & Rekap Rutin*\n"
        "• ⏰ *Alarm & Pengingat Acara*\n"
        "• 📋 *To-do List & Catatan*\n\n"
        "Ada yang bisa gue bantu sekarang, bor?"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("harga"))
@dp.message(Command("pricelist"))
async def cmd_harga(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1:
        query = parts[1].strip()
        ans = pricelist.query_pricelist_tool(query)
        await message.answer(ans, reply_markup=get_main_keyboard())
    else:
        await message.answer(
            "🏷️ *CEK HARGA PRICELIST (ADP)*\n\n"
            "Ketik tipe/kode produk di chat, contoh:\n"
            "• `EW1200G` atau `/harga EW1200G`\n"
            "• `RG-RAP2260`\n"
            "• Atau tanya: _\"Harga EW3000GX beli 5 unit diskon 5%?\"_",
            reply_markup=get_main_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )

@dp.message(Command("setharga"))
@dp.message(Command("updateharga"))
@dp.message(Command("ubahharga"))
@dp.message(Command("gantiharga"))
async def cmd_set_harga(message: Message):
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        guide = (
            "🛠️ *FITUR UBAH / PERBAIKI HARGA CEPAT*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Lu bisa langsung perbaiki atau update harga produk di database, bor!\n\n"
            "📌 *1. Ubah 1 Produk:*\n"
            "• `/setharga RG-RAP2260 4908420`\n"
            "• `/setharga DH-IPC-HFW1230 475.324`\n"
            "• Atau ketik biasa di chat: `ubah harga RG-RAP2260 jadi 4908420`\n\n"
            "📌 *2. Ubah Banyak Sekaligus:*\n"
            "Ketik perintah diikuti daftar tipe & harga:\n"
            "```\n"
            "/setharga\n"
            "RG-RAP62-OD 2035740\n"
            "RG-RAP2260 4908420\n"
            "DH-IPC-HFW1230 475324\n"
            "```\n"
            "_Harga langsung tersimpan permanen di database pricelist!_ 🚀"
        )
        await message.answer(guide, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return

    content = parts[1].strip()
    lines = [l for l in content.splitlines() if l.strip()]
    if len(lines) > 1:
        ok, res_text, count = pricelist.batch_update_product_prices(content)
        await message.answer(res_text, reply_markup=get_main_keyboard())
        return

    m = re.search(r'^(.*?)(?::\s*|=\s*|\s+(?:jadi|menjadi)\s*|\s+)(?:Rp\.?\s*)?([0-9\.\,]+)$', content, flags=re.IGNORECASE)
    if m:
        model = m.group(1).strip()
        price = m.group(2).strip()
        ok, res_text = pricelist.update_product_price(model, price)
        await message.answer(res_text, reply_markup=get_main_keyboard())
    else:
        ok, res_text, count = pricelist.batch_update_product_prices(content)
        if ok:
            await message.answer(res_text, reply_markup=get_main_keyboard())
        else:
            await message.answer(
                "⚠️ Format salah, bor. Gunakan format:\n"
                "`/setharga <tipe> <harga>`\n"
                "Contoh: `/setharga RG-RAP2260 4908420`",
                parse_mode=ParseMode.MARKDOWN
            )

@dp.message(Command("notifikasi"))
@dp.message(Command("notif"))
async def cmd_notifikasi(message: Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Teman"
    db.register_or_update_user(user_id, user_name, message.chat.id)
    settings = db.get_notification_settings(user_id)
    kb = notifications.get_notification_settings_keyboard(settings)
    sched_day = settings.get('scheduled_day', 25)
    daily_time = settings.get('daily_recap_time', '22:00')
    text = (
        "🔔 *NOTIFIKASI CERDAS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• 🌙 *Daily Recap* ({daily_time} WIB / Jam 10 Malam)\n"
        "• 📅 *Weekly Recap* (Senin 07:30 WIB)\n"
        "• 📑 *Monthly Report* (Tgl 1 08:00 WIB)\n"
        f"• ⏰ *Scheduled Report* (Tgl {sched_day} 08:30 WIB)\n"
        "• ⏰ *Alarm & Pengingat*: Aktif otomatis real-time\n\n"
        "Aktifkan / nonaktifkan fitur di bawah:"
    )
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("kalender"))
@dp.message(Command("agenda"))
async def cmd_kalender(message: Message):
    user_id = message.from_user.id
    now = notifications.get_now_wib()
    cal_view = db.render_calendar_view(user_id, now.year, now.month)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔙 Kembali ke Menu", callback_data="menu_help")
            ]
        ]
    )
    await message.answer(
        f"{cal_view}\n\n_Ketik 'tambahkan agenda [nama acara] tanggal YYYY-MM-DD' atau langsung minta di chat._",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(Command("pengingat"))
@dp.message(Command("alarm"))
async def cmd_pengingat(message: Message):
    user_id = message.from_user.id
    rems = db.get_user_reminders(user_id, status='pending')
    if not rems:
        await message.answer(
            "⏰ *ALARM & PENGINGAT*\n━━━━━━━━━━━━━━━━━━━━━━\n"
            "Belum ada alarm atau pengingat aktif.\n\n"
            "💡 *Cara memasang alarm/pengingat:*\n"
            "• _'Ingatkan meeting jam 2 siang'_\n"
            "• _'Ingatkan besok jam 10 pagi zoom meeting'_\n"
            "• _'Pasang alarm 30 menit lagi untuk jemput paket'_",
            reply_markup=get_main_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return
        
    lines = ["⏰ *DAFTAR ALARM & PENGINGAT AKTIF:*", "━━━━━━━━━━━━━━━━━━━━━━"]
    for r in rems:
        lines.append(f"• [ID #{r['id']}] *{r['title']}* (🕒 {r['remind_at']} WIB)")
    lines.append("\n_Ketik 'batalkan pengingat [ID]' untuk membatalkan._")
    await message.answer("\n".join(lines), reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("tesnotif"))
@dp.message(Command("tes_notif"))
async def cmd_tes_notif(message: Message, bot: Bot):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Teman"
    db.register_or_update_user(user_id, user_name, message.chat.id)
    await notifications.send_test_notification(bot, user_id, message.chat.id, user_name)

@dp.message(Command("keuangan"))
async def cmd_keuangan(message: Message):
    user_id = message.from_user.id
    summary = finance.generate_balance_summary(user_id)
    await message.answer(summary, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("laporan"))
async def cmd_laporan(message: Message):
    user_id = message.from_user.id
    report = finance.generate_financial_report(user_id, "month")
    await message.answer(report, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)


async def send_excel_selection_or_direct(target, user_id: int):
    last_pdf = pdf_converter.user_last_pdf.get(user_id)
    if last_pdf and os.path.exists(last_pdf.get("excel_path", "")):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"📄 Excel dari PDF ({last_pdf['file_name'][:20]})",
                        callback_data="dl_excel_pdf"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="💼 Excel Catatan Harian (Database)",
                        callback_data="dl_excel_db"
                    )
                ]
            ]
        )
        msg_text = (
            "📊 *PILIHAN FILE EXCEL*\n\n"
            f"1️⃣ *PDF Terakhir:* `{last_pdf['file_name']}`\n"
            "2️⃣ *Database Harian:* Catatan pembukuan bot\n\n"
            "Pilih file yang ingin diunduh:"
        )
        if isinstance(target, CallbackQuery):
            await target.message.answer(msg_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        else:
            await target.answer(msg_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        status_msg = None
        send_target = target.message if isinstance(target, CallbackQuery) else target
        try:
            status_msg = await send_target.answer("⏳ Menyiapkan file Excel...")
            excel_path = finance.export_financial_report_excel(user_id, "all")
            await send_target.answer_document(
                FSInputFile(excel_path),
                caption="📊 Rekap Transaksi (Database)",
                reply_markup=get_main_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Gagal kirim dokumen excel: {e}")
            await send_target.answer(f"Gagal membuat excel: {e}")
        finally:
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

@dp.message(Command("excel"))
@dp.message(Command("export"))
async def cmd_excel(message: Message):
    user_id = message.from_user.id
    await send_excel_selection_or_direct(message, user_id)


@dp.message(Command("resetsaldo"))
@dp.message(Command("resetkeuangan"))
async def cmd_reset_saldo(message: Message):
    user_id = message.from_user.id
    count = db.reset_user_finances(user_id)
    await message.answer(
        f"🗑️ *Saldo Direset!*\n\n"
        f"• Transaksi dihapus: {count}\n"
        f"• Saldo saat ini: `Rp 0`",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(Command("tugas"))
async def cmd_tugas(message: Message):
    user_id = message.from_user.id
    tasks = db.get_tasks(user_id, status="pending")
    if not tasks:
        await message.answer("🎉 Semua tugas sudah selesai! Belum ada to-do list baru.\n_Ketik 'tambah tugas [nama tugas]' untuk membuat baru._", parse_mode=ParseMode.MARKDOWN)
        return
    lines = ["📋 *DAFTAR TUGAS BELUM SELESAI:*", "━━━━━━━━━━━━━━━━━━━━━━"]
    for t in tasks:
        dl = f" (⏰ {t['due_date']})" if t['due_date'] else ""
        lines.append(f"• [ID #{t['id']}] {t['title']}{dl}")
    lines.append("\n_Ketik 'selesaikan tugas ID' atau 'hapus tugas ID' untuk memperbarui._")
    await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("catatan"))
async def cmd_catatan(message: Message):
    user_id = message.from_user.id
    notes = db.get_notes(user_id, limit=10)
    if not notes:
        await message.answer("📝 Belum ada catatan tersimpan.\n_Ketik 'Catat: [isi memo]' untuk menyimpan catatan baru._", parse_mode=ParseMode.MARKDOWN)
        return
    lines = ["📝 *CATATAN TERSIMPAN:*", "━━━━━━━━━━━━━━━━━━━━━━"]
    for n in notes:
        title = f"*{n['title']}*: " if n['title'] else ""
        lines.append(f"• [#{n['id']}] {title}{n['content']} ({n['created_at'][:10]})")
    await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("help"))
@dp.message(Command("bantuan"))
async def cmd_help(message: Message):
    help_text = (
        "💡 *PANDUAN PENGGUNAAN ASISTEN AI*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Anda bisa berbicara dengan bahasa santai sehari-hari melalui teks atau pesan suara:\n\n"
        "💰 *Contoh Catat Keuangan:*\n"
        "• _'Tadi makan siang nasi padang 25rb'_\n"
        "• _'Isi bensin motor 35.000'_\n"
        "• _'Dapat transferan gaji 6.000.000'_\n"
        "• _'Sisa uang saya tinggal berapa?'_\n"
        "• _'Buatkan laporan keuangan bulan ini'_\n\n"
        "📋 *Contoh Tugas & Catatan:*\n"
        "• _'Catat tugas beli susu anak pulang kerja nanti'_\n"
        "• _'Ingatkan besok jam 10 pagi ada zoom'_\n"
        "• _'Lihat daftar tugas saya'_\n"
        "• _'Tandai tugas #1 sudah selesai'_\n"
        "• _'Simpan catatan: password wifi kantor xyz123'_\n\n"
        "🎙️ *Pesan Suara (Voice Note):*\n"
        "• Tahan tombol mikrofon di Telegram dan ucapkan pengeluaran atau pertanyaan Anda langsung. AI akan memproses dan membalas dengan teks & suara!\n"
    )
    await message.answer(help_text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query()
async def handle_callbacks(callback: CallbackQuery, bot: Bot):
    data = callback.data
    user_id = callback.from_user.id
    await callback.answer()

    if data == "menu_saldo":
        text = finance.generate_balance_summary(user_id)
        await callback.message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_lap_month":
        text = finance.generate_financial_report(user_id, "month")
        await callback.message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_lap_today":
        text = finance.generate_financial_report(user_id, "today")
        await callback.message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_lap_week":
        text = finance.generate_financial_report(user_id, "week")
        await callback.message.answer(text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_tasks":
        tasks = db.get_tasks(user_id, status="pending")
        if not tasks:
            await callback.message.answer("🎉 Semua tugas sudah selesai!", reply_markup=get_main_keyboard())
        else:
            lines = ["📋 *DAFTAR TUGAS AKTIF:*"]
            for t in tasks:
                lines.append(f"• [#{t['id']}] {t['title']}")
            await callback.message.answer("\n".join(lines), reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_notes":
        notes = db.get_notes(user_id, limit=8)
        if not notes:
            await callback.message.answer("📝 Belum ada catatan.", reply_markup=get_main_keyboard())
        else:
            lines = ["📝 *CATATAN:*"]
            for n in notes:
                lines.append(f"• {n['content']}")
            await callback.message.answer("\n".join(lines), reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_excel":
        await send_excel_selection_or_direct(callback, user_id)
    elif data == "menu_harga":
        await callback.message.answer(
            "🏷️ *CEK HARGA PRICELIST (ADP)*\n\n"
            "Ketik tipe/kode produk di chat, contoh:\n"
            "• `EW1200G` atau `/harga EW1200G`\n"
            "• `RG-RAP2260`\n"
            "• Atau tanya: _\"Harga EW3000GX beli 5 unit diskon 5%?\"_",
            reply_markup=get_main_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "dl_excel_pdf":
        last_pdf = pdf_converter.user_last_pdf.get(user_id)
        if last_pdf and os.path.exists(last_pdf.get("excel_path", "")):
            await callback.message.answer_document(
                FSInputFile(last_pdf["excel_path"]),
                caption=(
                    f"📊 *File Excel dari Laporan PDF:*\n"
                    f"📁 `{last_pdf['file_name']}`\n\n"
                    f"_File ini dibuat khusus dari data dokumen PDF Anda tanpa mengubah database pembukuan harian._"
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await callback.message.answer("⚠️ File Excel dari PDF belum tersedia di sesi ini. Silakan kirimkan file PDF Anda terlebih dahulu ya!")
    elif data == "dl_excel_db":
        msg = await callback.message.answer("⏳ Sedang menyiapkan laporan keuangan database...")
        try:
            excel_path = finance.export_financial_report_excel(user_id, "all")
            await callback.message.answer_document(
                FSInputFile(excel_path),
                caption="📊 *File Laporan Keuangan Harian (Database Bot)*\n_Berikut rekap catatan pembukuan harian Anda._",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await callback.message.answer(f"Gagal mengekspor database: {e}")
        finally:
            try:
                await msg.delete()
            except Exception:
                pass
    elif data == "menu_resetsaldo":
        count = db.reset_user_finances(user_id)
        await callback.message.answer(
            f"🗑️ *BERHASIL RESET KEUANGAN*\n\n"
            f"Sebanyak {count} transaksi telah dihapus.\n"
            f"💰 *Saldo saat ini:* `Rp 0`\n"
            f"📥 *Total Pemasukan:* `Rp 0`\n"
            f"📤 *Total Pengeluaran:* `Rp 0`\n\n"
            f"_Pembukuan keuangan Anda sekarang bersih dan siap dimulai dari awal!_",
            reply_markup=get_main_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "menu_kalender":
        now = notifications.get_now_wib()
        cal_view = db.render_calendar_view(user_id, now.year, now.month)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🔙 Kembali ke Menu", callback_data="menu_help")
                ]
            ]
        )
        await callback.message.answer(
            f"{cal_view}\n\n_Ketik 'tambahkan agenda [nama acara] tanggal YYYY-MM-DD' atau langsung minta di chat._",
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "menu_pengingat":
        rems = db.get_user_reminders(user_id, status='pending')
        if not rems:
            await callback.message.answer(
                "⏰ *ALARM & PENGINGAT*\n━━━━━━━━━━━━━━━━━━━━━━\n"
                "Belum ada alarm atau pengingat aktif.\n\n"
                "💡 *Cara memasang alarm/pengingat:*\n"
                "• _'Ingatkan meeting jam 2 siang'_\n"
                "• _'Ingatkan besok jam 10 pagi zoom meeting'_\n"
                "• _'Pasang alarm 30 menit lagi untuk jemput paket'_",
                reply_markup=get_main_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            lines = ["⏰ *DAFTAR ALARM & PENGINGAT AKTIF:*", "━━━━━━━━━━━━━━━━━━━━━━"]
            for r in rems:
                lines.append(f"• [ID #{r['id']}] *{r['title']}* (🕒 {r['remind_at']} WIB)")
            lines.append("\n_Ketik 'batalkan pengingat [ID]' untuk membatalkan._")
            await callback.message.answer("\n".join(lines), reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
    elif data == "menu_notifikasi":
        user_name = callback.from_user.first_name or "Teman"
        db.register_or_update_user(user_id, user_name, callback.message.chat.id)
        settings = db.get_notification_settings(user_id)
        kb = notifications.get_notification_settings_keyboard(settings)
        sched_day = settings.get('scheduled_day', 25)
        daily_time = settings.get('daily_recap_time', '22:00')
        text = (
            "🔔 *PENGATURAN NOTIFIKASI CERDAS SELOBROW*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Selobrow dapat mengirimkan rekapitulasi & laporan keuangan otomatis:\n\n"
            f"• 🌙 *Daily Recap* ({daily_time} WIB / Jam 10 Malam): Evaluasi pengeluaran hari ini.\n"
            "• 📅 *Weekly Recap* (Senin 07:30 WIB): Evaluasi keuangan selama 7 hari terakhir.\n"
            "• 📑 *Monthly Report* (Tanggal 1 08:00 WIB): Rekap bulanan lengkap + analisis AI + lampiran file Excel.\n"
            f"• ⏰ *Scheduled Reports* (Tanggal {sched_day} 08:30 WIB): Laporan terjadwal otomatis pada tanggal pilihan Anda.\n"
            "• ⏰ *Alarm & Pengingat*: Berbunyi otomatis real-time saat jam tiba.\n\n"
            "Silakan klik tombol di bawah untuk menyalakan/mematikan fitur atau mengubah tanggal terjadwal:"
        )
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    elif data == "toggle_notif_daily":
        settings = db.get_notification_settings(user_id)
        new_val = 0 if settings.get('daily_recap_enabled') else 1
        db.update_notification_setting(user_id, 'daily_recap_enabled', new_val)
        updated = db.get_notification_settings(user_id)
        kb = notifications.get_notification_settings_keyboard(updated)
        await callback.message.edit_reply_markup(reply_markup=kb)
        st_text = "diaktifkan ✅" if new_val else "dinonaktifkan ❌"
        await callback.answer(f"Rekap Harian {st_text}")
    elif data == "toggle_notif_weekly":
        settings = db.get_notification_settings(user_id)
        new_val = 0 if settings.get('weekly_recap_enabled') else 1
        db.update_notification_setting(user_id, 'weekly_recap_enabled', new_val)
        updated = db.get_notification_settings(user_id)
        kb = notifications.get_notification_settings_keyboard(updated)
        await callback.message.edit_reply_markup(reply_markup=kb)
        st_text = "diaktifkan ✅" if new_val else "dinonaktifkan ❌"
        await callback.answer(f"Rekap Mingguan {st_text}")
    elif data == "toggle_notif_monthly":
        settings = db.get_notification_settings(user_id)
        new_val = 0 if settings.get('monthly_report_enabled') else 1
        db.update_notification_setting(user_id, 'monthly_report_enabled', new_val)
        updated = db.get_notification_settings(user_id)
        kb = notifications.get_notification_settings_keyboard(updated)
        await callback.message.edit_reply_markup(reply_markup=kb)
        st_text = "diaktifkan ✅" if new_val else "dinonaktifkan ❌"
        await callback.answer(f"Laporan Bulanan {st_text}")
    elif data == "toggle_notif_scheduled":
        settings = db.get_notification_settings(user_id)
        new_val = 0 if settings.get('scheduled_reports_enabled') else 1
        db.update_notification_setting(user_id, 'scheduled_reports_enabled', new_val)
        updated = db.get_notification_settings(user_id)
        kb = notifications.get_notification_settings_keyboard(updated)
        await callback.message.edit_reply_markup(reply_markup=kb)
        st_text = "diaktifkan ✅" if new_val else "dinonaktifkan ❌"
        await callback.answer(f"Laporan Terjadwal {st_text}")
    elif data == "menu_change_sched_day":
        days = [1, 5, 10, 15, 20, 25, 28, 30]
        rows = []
        cur_row = []
        for d in days:
            cur_row.append(InlineKeyboardButton(text=f"Tgl {d}", callback_data=f"set_sched_day_{d}"))
            if len(cur_row) == 4:
                rows.append(cur_row)
                cur_row = []
        if cur_row:
            rows.append(cur_row)
        rows.append([InlineKeyboardButton(text="🔙 Batal / Kembali", callback_data="menu_notifikasi")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
        await callback.message.edit_text(
            "🗓️ *PILIH TANGGAL LAPORAN TERJADWAL*\n\n"
            "Pilih tanggal setiap bulan saat Anda ingin menerima laporan keuangan otomatis (contoh: tanggal gajian atau evaluasi tagihan):",
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN
        )
    elif data.startswith("set_sched_day_"):
        day_val = int(data.replace("set_sched_day_", ""))
        db.update_notification_setting(user_id, 'scheduled_day', day_val)
        db.update_notification_setting(user_id, 'scheduled_reports_enabled', 1)
        updated = db.get_notification_settings(user_id)
        kb = notifications.get_notification_settings_keyboard(updated)
        text = (
            f"✅ *Tanggal Terjadwal Berhasil Disimpan!*\n\n"
            f"Laporan otomatis akan dikirimkan setiap **tanggal {day_val}** pukul 08:30 WIB.\n\n"
            "Pengaturan notifikasi saat ini:"
        )
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        await callback.answer(f"Tanggal diubah ke {day_val}")
    elif data == "menu_help":
        await cmd_help(callback.message)
    elif data == "test_notif_now":
        user_name = callback.from_user.first_name or "Teman"
        db.register_or_update_user(user_id, user_name, callback.message.chat.id)
        await callback.answer("Mengirim tes notifikasi... ⏳")
        await notifications.send_test_notification(bot, user_id, callback.message.chat.id, user_name)
    elif data.startswith("auth_approve_"):
        target_uid = int(data.replace("auth_approve_", ""))
        is_owner = (ADMIN_USER_ID and str(user_id) == str(ADMIN_USER_ID)) or any(o["user_id"] == user_id for o in db.get_owners())
        if not is_owner:
            await callback.answer("Hanya pemilik bot yang berhak memberikan izin akses.", show_alert=True)
            return

        db.approve_user(target_uid)
        target_info = db.get_user_auth(target_uid)
        t_chat_id = target_info.get("chat_id", target_uid) if target_info else target_uid

        new_text = f"{callback.message.text}\n\n✅ *STATUS: DISETUJUI*\n_Akses telah diizinkan oleh {callback.from_user.first_name}._"
        try:
            await callback.message.edit_text(new_text, reply_markup=None, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
        await callback.answer("Pengguna berhasil disetujui! ✅")

        try:
            welcome_msg = (
                "🎉 *Selamat! Permintaan akses Anda telah disetujui.*\n\n"
                "Anda sekarang dapat menggunakan asisten AI Selobrow untuk cek harga, pencatatan keuangan, voice note, dan lainnya.\n\n"
                "Ketik /help atau kirim pesan apa saja untuk memulai! 🚀"
            )
            await bot.send_message(t_chat_id, welcome_msg, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"Gagal mengirim notifikasi persetujuan ke user {target_uid}: {e}")

    elif data.startswith("auth_reject_"):
        target_uid = int(data.replace("auth_reject_", ""))
        is_owner = (ADMIN_USER_ID and str(user_id) == str(ADMIN_USER_ID)) or any(o["user_id"] == user_id for o in db.get_owners())
        if not is_owner:
            await callback.answer("Hanya pemilik bot yang berhak menolak akses.", show_alert=True)
            return

        db.reject_user(target_uid)
        target_info = db.get_user_auth(target_uid)
        t_chat_id = target_info.get("chat_id", target_uid) if target_info else target_uid

        new_text = f"{callback.message.text}\n\n❌ *STATUS: DITOLAK*\n_Permintaan akses ditolak oleh {callback.from_user.first_name}._"
        try:
            await callback.message.edit_text(new_text, reply_markup=None, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
        await callback.answer("Pengguna telah ditolak. ❌")

        try:
            await bot.send_message(t_chat_id, "❌ Maaf, permohonan akses Anda untuk bot ini telah ditolak oleh pemilik.")
        except Exception:
            pass


@dp.message(Command("pengguna"))
@dp.message(Command("users"))
async def cmd_users(message: Message):
    user_id = message.from_user.id
    is_owner = (ADMIN_USER_ID and str(user_id) == str(ADMIN_USER_ID)) or any(o["user_id"] == user_id for o in db.get_owners())
    if not is_owner:
        await message.answer("❌ Perintah ini khusus untuk pemilik bot.")
        return

    users = db.get_all_authorized_users()
    if not users:
        await message.answer("Belum ada data pengguna yang tersimpan.")
        return

    text = "👥 *DAFTAR PENGGUNA BOT PRIVAT*\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for u in users:
        if u.get("role") == "owner":
            status_icon = "👑 Owner"
        elif u.get("status") == "approved":
            status_icon = "✅ Aktif"
        elif u.get("status") == "pending":
            status_icon = "⏳ Menunggu Izin"
        else:
            status_icon = "❌ Ditolak"

        uname = f"@{u['username']}" if u.get("username") else "-"
        text += (
            f"• *{u.get('user_name', 'Tanpa Nama')}* ({uname})\n"
            f"  ID: `{u['user_id']}` | Status: {status_icon}\n"
        )
    text += "\n_Perintah Pengelola:_\n• `/izinkan <user_id>` untuk memberi izin\n• `/cabut <user_id>` untuk menolak/mencabut akses"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@dp.message(Command("izinkan"))
async def cmd_izinkan(message: Message, bot: Bot):
    user_id = message.from_user.id
    is_owner = (ADMIN_USER_ID and str(user_id) == str(ADMIN_USER_ID)) or any(o["user_id"] == user_id for o in db.get_owners())
    if not is_owner:
        await message.answer("❌ Perintah ini khusus untuk pemilik bot.")
        return

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Format salah. Gunakan: `/izinkan <user_id>`\nContoh: `/izinkan 123456789`", parse_mode=ParseMode.MARKDOWN)
        return

    target_uid = int(parts[1])
    db.approve_user(target_uid)
    await message.answer(f"✅ User `{target_uid}` berhasil disetujui & diberikan akses!", parse_mode=ParseMode.MARKDOWN)

    target_info = db.get_user_auth(target_uid)
    t_chat_id = target_info.get("chat_id", target_uid) if target_info else target_uid
    try:
        await bot.send_message(
            t_chat_id,
            "🎉 *Selamat! Akses bot Anda telah diaktifkan oleh pemilik.*\nKetik /help untuk panduan penggunaan.",
            reply_markup=get_main_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        pass


@dp.message(Command("cabut"))
async def cmd_cabut(message: Message, bot: Bot):
    user_id = message.from_user.id
    is_owner = (ADMIN_USER_ID and str(user_id) == str(ADMIN_USER_ID)) or any(o["user_id"] == user_id for o in db.get_owners())
    if not is_owner:
        await message.answer("❌ Perintah ini khusus untuk pemilik bot.")
        return

    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Format salah. Gunakan: `/cabut <user_id>`\nContoh: `/cabut 123456789`", parse_mode=ParseMode.MARKDOWN)
        return

    target_uid = int(parts[1])
    if str(target_uid) == str(user_id) or (ADMIN_USER_ID and str(target_uid) == str(ADMIN_USER_ID)):
        await message.answer("❌ Tidak dapat mencabut akses akun pemilik bot sendiri.")
        return

    db.reject_user(target_uid)
    await message.answer(f"🚫 Akses user `{target_uid}` berhasil dicabut/ditolak!", parse_mode=ParseMode.MARKDOWN)

    target_info = db.get_user_auth(target_uid)
    t_chat_id = target_info.get("chat_id", target_uid) if target_info else target_uid
    try:
        await bot.send_message(t_chat_id, "🔒 Akses Anda ke bot ini telah dinonaktifkan oleh pemilik.")
    except Exception:
        pass


@dp.message(F.voice)
async def handle_voice_message(message: Message, bot: Bot):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Teman"

    # Indikator bot sedang merekam/memproses
    await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")

    temp_voice_path = None
    try:
        # Download voice note dari Telegram
        file = await bot.get_file(message.voice.file_id)
        voice_io = io.BytesIO()
        await bot.download_file(file.file_path, destination=voice_io)
        voice_bytes = voice_io.getvalue()

        # Proses dengan Gemini AI
        reply_text = await gemini_agent.process_user_voice(
            user_id=user_id,
            user_name=user_name,
            voice_bytes=voice_bytes,
            mime_type="audio/ogg",
            chat_id=message.chat.id
        )

        # Kirim balasan teks
        try:
            await message.answer(reply_text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await message.answer(reply_text)

        # Jika suara balasan aktif, buatkan audio balasan TTS
        if VOICE_REPLY_ENABLED:
            try:
                await bot.send_chat_action(chat_id=message.chat.id, action="record_voice")
                audio_file = await tts.text_to_speech_audio(reply_text)
                temp_voice_path = audio_file
                voice_input = FSInputFile(audio_file)
                await message.answer_voice(voice_input)
            except Exception as tts_err:
                logger.error(f"Gagal mengirim balasan suara TTS: {tts_err}")

    except Exception as e:
        logger.error(f"Gagal memproses voice note: {e}", exc_info=True)
        await message.answer(f"Maaf, gagal memproses pesan suara: {e}")
    finally:
        if temp_voice_path:
            tts.cleanup_audio_file(temp_voice_path)

@dp.message(F.photo)
async def handle_photo_message(message: Message, bot: Bot):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Teman"
    caption = message.caption or ""

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        photo = message.photo[-1]
        photo_file = await bot.get_file(photo.file_id)
        
        photo_io = io.BytesIO()
        await bot.download_file(photo_file.file_path, destination=photo_io)
        image_bytes = photo_io.getvalue()

        reply_text = await gemini_agent.process_user_image(
            user_id=user_id,
            user_name=user_name,
            image_bytes=image_bytes,
            mime_type="image/jpeg",
            caption=caption,
            chat_id=message.chat.id
        )

        try:
            await message.answer(reply_text, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await message.answer(reply_text)
    except Exception as e:
        logger.error(f"Gagal memproses foto: {e}", exc_info=True)
        await message.answer(f"Maaf, gagal memproses foto: {e}")

@dp.message(F.document)
async def handle_document_message(message: Message, bot: Bot):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Teman"
    caption = message.caption or ""
    doc = message.document

    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        doc_file = await bot.get_file(doc.file_id)
        doc_io = io.BytesIO()
        await bot.download_file(doc_file.file_path, destination=doc_io)
        doc_bytes = doc_io.getvalue()

        mime_type = doc.mime_type or "application/pdf"
        file_name = doc.file_name or "dokumen.pdf"

        # Jika pengguna mengirim gambar dalam bentuk dokumen file
        if mime_type.startswith("image/"):
            reply_text = await gemini_agent.process_user_image(
                user_id=user_id,
                user_name=user_name,
                image_bytes=doc_bytes,
                mime_type=mime_type,
                caption=caption,
                chat_id=message.chat.id
            )
        elif file_name.lower().endswith(".csv") or mime_type == "text/csv":
            try:
                csv_text = doc_bytes.decode("utf-8")
            except Exception:
                csv_text = doc_bytes.decode("latin-1", errors="ignore")
            ok, msg, count = pricelist.save_new_pricelist_csv(csv_text)
            if ok:
                await message.answer(
                    f"✅ *Pricelist Berhasil Diperbarui!*\n\n"
                    f"• {msg}\n"
                    f"• Total `{count}` produk kini siap dicari harganya (ADP-Price).",
                    reply_markup=get_main_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await message.answer(f"⚠️ Gagal memperbarui pricelist: {msg}")
            return
        elif file_name.lower().endswith((".xlsx", ".xls")) or "spreadsheet" in mime_type or "excel" in mime_type:
            # 1. Coba deteksi apakah ini file pricelist produk
            ok, msg, count = pricelist.import_pricelist_from_excel(doc_bytes, file_name)
            if ok:
                total_all = len(pricelist.load_pricelist())
                await message.answer(
                    f"✅ *Pricelist Excel Berhasil Diperbarui!*\n\n"
                    f"• {msg}\n"
                    f"• Total `{total_all}` produk kini tersimpan di database harga (Hikvision / Ruijie / Dahua).\n"
                    f"Ketik tipe produk kapan saja untuk cek harga!",
                    reply_markup=get_main_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            # 2. Jika bukan pricelist, analisis isi data spreadsheet
            status_msg = await message.answer(f"⏳ Membaca dan menganalisis spreadsheet `{file_name}`...", parse_mode=ParseMode.MARKDOWN)
            excel_text = pricelist.extract_text_from_excel(doc_bytes)
            if not excel_text:
                await status_msg.edit_text(f"⚠️ Gagal membaca data dari `{file_name}`.")
                return

            user_prompt = f"Analisis file spreadsheet Excel '{file_name}'. Catatan: '{caption}'. Ringkas data atau jawab pertanyaan secara singkat dan jelas:\n\n{excel_text[:10000]}"
            analysis_reply = await gemini_agent.process_user_text(user_id, user_name, user_prompt, chat_id=message.chat.id)

            try:
                await message.answer(f"📊 *Ringkasan Spreadsheet:* `{file_name}`\n\n{analysis_reply}", parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await message.answer(f"📊 Ringkasan Spreadsheet: {file_name}\n\n{analysis_reply}")

            try:
                await status_msg.delete()
            except Exception:
                pass
            return
        else:
            status_msg = await message.answer(
                f"⏳ Memproses PDF `{file_name}` ke Excel...",
                parse_mode=ParseMode.MARKDOWN
            )
            summary_text, excel_path = await pdf_converter.convert_pdf_document_to_excel(
                doc_bytes=doc_bytes,
                file_name=file_name,
                caption=caption,
                user_id=user_id
            )

            try:
                await message.answer(summary_text, parse_mode=ParseMode.MARKDOWN)
            except Exception:
                await message.answer(summary_text)

            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="💼 Download Excel Database Harian",
                            callback_data="dl_excel_db"
                        )
                    ]
                ]
            )

            await message.answer_document(
                FSInputFile(excel_path),
                caption=f"📊 Excel: `{file_name}`",
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )

            try:
                await status_msg.delete()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Gagal memproses dokumen: {e}", exc_info=True)
        err_msg = str(e)
        if "file is too big" in err_msg.lower():
            await message.answer(
                f"⚠️ *Ukuran File Terlalu Besar ({file_name})*\n\n"
                "Telegram Bot membatasi unduhan file maksimal **20 MB** (file ini sekitar 26.8 MB karena ada foto produk di dalamnya).\n\n"
                "💡 *Tips:* Simpan file Excel Anda sebagai format **.CSV** (File -> Save As -> CSV UTF-8). Ukurannya akan mengecil di bawah 1 MB dan langsung bisa dibaca bot!",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await message.answer(f"Maaf, terjadi kendala saat memproses dokumen: {e}")


@dp.message(F.text)
async def handle_text_message(message: Message, bot: Bot):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Teman"
    user_text = message.text

    # Indikator typing
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Intersep langsung perintah reset saldo
    lower_text = user_text.strip().lower()
    if "reset saldo" in lower_text or "reset keuangan" in lower_text or lower_text in ["/resetsaldo", "/resetkeuangan"]:
        count = db.reset_user_finances(user_id)
        await message.answer(
            f"🗑️ *BERHASIL RESET KEUANGAN*\n\n"
            f"Sebanyak {count} transaksi telah dihapus.\n"
            f"💰 *Saldo saat ini:* `Rp 0`\n"
            f"📥 *Total Pemasukan:* `Rp 0`\n"
            f"📤 *Total Pengeluaran:* `Rp 0`\n\n"
            f"_Pembukuan keuangan Anda sekarang bersih dan siap dimulai dari awal!_",
            reply_markup=get_main_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Intersep langsung update / perbaiki harga (natural language & multi-line)
    if re.search(r'^(?:/setharga|/updateharga|/ubahharga|/gantiharga|ubah harga|ganti harga|update harga|set harga|perbaiki harga|benerin harga)\b', lower_text):
        lines = [l for l in user_text.strip().splitlines() if l.strip()]
        if len(lines) > 1:
            ok, res_msg, count = pricelist.batch_update_product_prices(user_text)
            await message.answer(res_msg, reply_markup=get_main_keyboard())
            return
        else:
            line_clean = re.sub(r'^(?:/setharga|/updateharga|/ubahharga|/gantiharga|ubah harga|ganti harga|update harga|set harga|perbaiki harga|benerin harga)[:\s]*', '', user_text, flags=re.IGNORECASE).strip()
            m = re.search(r'^(.*?)(?::\s*|=\s*|\s+(?:jadi|menjadi)\s*|\s+)(?:Rp\.?\s*)?([0-9\.\,]+)$', line_clean, flags=re.IGNORECASE)
            if m:
                model = m.group(1).strip()
                price = m.group(2).strip()
                ok, res_msg = pricelist.update_product_price(model, price)
                await message.answer(res_msg, reply_markup=get_main_keyboard())
                return
            else:
                ok, res_msg, count = pricelist.batch_update_product_prices(user_text)
                if ok:
                    await message.answer(res_msg, reply_markup=get_main_keyboard())
                    return

    # Intersep langsung kueri kode model produk (Cek Harga Instan tanpa LLM)
    direct_price_ans = pricelist.try_direct_pricelist_query(user_text)
    if direct_price_ans:
        await message.answer(direct_price_ans, reply_markup=get_main_keyboard())
        return

    # Intersep permintaan Excel khusus dari PDF
    if any(k in lower_text for k in ["excel pdf", "excel dari pdf", "laporan pdf excel", "unduh excel pdf", "download excel pdf", "buatkan excel pdf"]):
        last_pdf = pdf_converter.user_last_pdf.get(user_id)
        if last_pdf and os.path.exists(last_pdf.get("excel_path", "")):
            await message.answer_document(
                FSInputFile(last_pdf["excel_path"]),
                caption=f"📊 *File Excel dari PDF: {last_pdf['file_name']}*\n_Dibuat khusus dari dokumen PDF Anda._",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        else:
            await message.answer(
                "⚠️ Belum ada file PDF yang Anda kirimkan pada sesi ini.\n\n"
                "Silakan langsung kirimkan file dokumen PDF (seperti laporan printing, invoice, atau mutasi bank) ke chat ini, dan saya akan otomatis membuatkan file Excel untuk Anda! 😊"
            )
            return

    # Intersep permintaan Excel Database harian
    if any(k in lower_text for k in ["excel database", "excel db", "excel harian", "laporan harian excel"]):
        msg = await message.answer("⏳ Sedang menyiapkan file Excel database...")
        try:
            excel_path = finance.export_financial_report_excel(user_id, "all")
            await message.answer_document(
                FSInputFile(excel_path),
                caption="📊 *File Laporan Keuangan Harian (Database)*\n_Berikut rekap catatan keuangan harian Anda._",
                parse_mode=ParseMode.MARKDOWN
            )
        finally:
            try:
                await msg.delete()
            except Exception:
                pass
        return

    # Intersep permintaan umum download/buat Excel
    if lower_text in [
        "/excel", "/export", "download excel", "download laporan excel",
        "📊 download laporan excel", "excel", "buatkan excel", "laporan excel",
        "buat excel", "kirim excel", "minta excel", "unduh excel"
    ]:
        await send_excel_selection_or_direct(message, user_id)
        return

    # Intersep permintaan pengaturan notifikasi cerdas
    if lower_text in [
        "/notifikasi", "/notif", "notifikasi", "pengaturan notifikasi",
        "🔔 notifikasi cerdas", "notifikasi cerdas", "atur notifikasi"
    ]:
        await cmd_notifikasi(message)
        return

    # Intersep tes notifikasi langsung
    if lower_text in [
        "/tesnotif", "/tes_notif", "tes notifikasi", "tes notif",
        "coba notifikasi", "test notifikasi", "test notif"
    ]:
        await cmd_tes_notif(message, bot)
        return

    # Intersep cepat menu kalender
    if lower_text in ["/kalender", "/agenda", "kalender", "agenda", "buka kalender", "lihat kalender"]:
        await cmd_kalender(message)
        return

    # Intersep cepat menu pengingat / alarm
    if lower_text in ["/pengingat", "/alarm", "pengingat", "alarm", "daftar alarm", "daftar pengingat", "cek alarm", "cek pengingat"]:
        await cmd_pengingat(message)
        return

    # Intersep panggilan nama bot atau sapaan santai
    if lower_text in ["bor", "bro", "selobrow", "halo", "hai", "p", "oi", "hey", "halo bor", "halo selobrow", "selamat pagi", "selamat siang", "selamat malam"]:
        welcome_greeting = (
            f"Yo *{user_name}*! 👋 Santai bor, ada apa nih?\n"
            "Selobrow siap bantu, mau ngapain kita hari ini?\n\n"
            "• Ketik tipe buat *Cek Harga*\n"
            "• Ketik pengeluaran/pemasukan buat *Catat Duit*\n"
            "• Ketik _'ingatkan...'_ buat *Pasang Alarm / Pengingat*\n"
            "• Ketik /kalender buat *Cek Agenda & Acara*"
        )
        await message.answer(welcome_greeting, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return

    # Registrasi user agar terdaftar di sistem notifikasi
    db.register_or_update_user(user_id, user_name, message.chat.id)

    reply_text = await gemini_agent.process_user_text(
        user_id=user_id,
        user_name=user_name,
        text=user_text,
        chat_id=message.chat.id
    )

    try:
        await message.answer(reply_text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        # Fallback jika ada karakter format telegram yang escape
        await message.answer(reply_text)

async def start_health_server():
    port_str = os.getenv("PORT")
    if not port_str:
        return
    try:
        from aiohttp import web
        port = int(port_str)
        async def handle_health(request):
            return web.Response(text="Bot Selobrow is running!", status=200)

        app = web.Application()
        app.router.add_get("/", handle_health)
        app.router.add_get("/health", handle_health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"Health check HTTP server berhasil aktif di port {port}")
    except Exception as e:
        logger.warning(f"Tidak dapat memulai health check HTTP server: {e}")

async def main():
    db.init_db()
    logger.info("Database SQLite berhasil diinisialisasi.")
    
    if not TELEGRAM_BOT_TOKEN or len(TELEGRAM_BOT_TOKEN) < 10:
        logger.error("="*60)
        logger.error("PERHATIAN FATAL: TELEGRAM_BOT_TOKEN belum disetel!")
        logger.error("Jika di Railway/Server, tambahkan TELEGRAM_BOT_TOKEN di menu Variables.")
        logger.error("Jika di lokal, masukkan ke file .env.")
        logger.error("="*60)
        raise ValueError("TELEGRAM_BOT_TOKEN belum disetel! Periksa environment variables / .env.")

    # Jalankan HTTP health check server jika ada PORT (untuk Railway / Render)
    await start_health_server()

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Menghapus webhook lama jika ada...")
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Memulai Background Notification Scheduler (Daily/Weekly Recap, Monthly Report, Scheduled Reports)...")
    asyncio.create_task(notifications.start_notification_scheduler(bot))

    # Pasang middleware hak akses privat
    dp.message.middleware(AccessControlMiddleware())
    dp.callback_query.middleware(AccessControlMiddleware())

    logger.info("Bot Telegram AI Selobrow siap beroperasi! Menunggu pesan...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

