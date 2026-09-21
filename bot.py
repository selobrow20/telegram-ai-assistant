import asyncio
import io
import logging
import os
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile
)

from config import TELEGRAM_BOT_TOKEN, VOICE_REPLY_ENABLED
import database as db
import finance
import gemini_agent
import tts
import pdf_converter
import notifications


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

def get_main_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="💰 Cek Saldo", callback_data="menu_saldo"),
            InlineKeyboardButton(text="📑 Laporan Bulan Ini", callback_data="menu_lap_month")
        ],
        [
            InlineKeyboardButton(text="📅 Laporan Hari Ini", callback_data="menu_lap_today"),
            InlineKeyboardButton(text="⏳ Laporan 7 Hari", callback_data="menu_lap_week")
        ],
        [
            InlineKeyboardButton(text="✅ Daftar To-Do", callback_data="menu_tasks"),
            InlineKeyboardButton(text="📝 Catatan Harian", callback_data="menu_notes")
        ],
        [
            InlineKeyboardButton(text="📥 Download Laporan Excel", callback_data="menu_excel"),
            InlineKeyboardButton(text="🔔 Notifikasi Cerdas", callback_data="menu_notifikasi")
        ],
        [
            InlineKeyboardButton(text="🗑️ Reset Saldo ke Rp 0", callback_data="menu_resetsaldo"),
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
        f"👋 Halo, *{user_name}*! Saya **Selobrow**, asisten AI pribadi Anda.\n\n"
        "Saya siap membantu kebutuhan sehari-hari Anda:\n"
        "🎙️ *Interaksi Suara & Teks*: Anda bisa mengetik atau langsung kirim **Voice Note** (pesan suara)!\n"
        "💸 *Catatan Keuangan Otomatis*: Cukup sebutkan pengeluaran/pemasukan Anda.\n"
        "📊 *Laporan Keuangan*: Pantau saldo, arus kas, dan rincian pengeluaran per kategori.\n"
        "🔔 *Notifikasi Cerdas*: Rekap pengeluaran harian, mingguan, bulanan, & tanggal gajian otomatis.\n"
        "📋 *To-Do & Catatan*: Simpan tugas, pengingat, dan ide penting kapan saja.\n"
        "🧠 *AI Bebas*: Tanyakan apa saja, mulai dari draf pesan hingga saran hidup.\n\n"
        "Silakan pilih menu cepat di bawah atau langsung ketik/kirim suara:"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("notifikasi"))
@dp.message(Command("notif"))
async def cmd_notifikasi(message: Message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Teman"
    db.register_or_update_user(user_id, user_name, message.chat.id)
    settings = db.get_notification_settings(user_id)
    kb = notifications.get_notification_settings_keyboard(settings)
    sched_day = settings.get('scheduled_day', 25)
    text = (
        "🔔 *PENGATURAN NOTIFIKASI CERDAS SELOBROW*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Selobrow dapat mengirimkan rekapitulasi & laporan keuangan otomatis:\n\n"
        "• ☀️ *Daily Recap* (07:00 WIB): Rincian pengeluaran kemarin (_'Kemarin kamu keluar Rp XX.XXX'_).\n"
        "• 📅 *Weekly Recap* (Senin 07:30 WIB): Evaluasi keuangan selama 7 hari terakhir.\n"
        "• 📑 *Monthly Report* (Tanggal 1 08:00 WIB): Rekap bulanan lengkap + analisis AI + lampiran file Excel.\n"
        f"• ⏰ *Scheduled Reports* (Tanggal {sched_day} 08:30 WIB): Laporan terjadwal otomatis pada tanggal pilihan Anda.\n\n"
        "Silakan klik tombol di bawah untuk menyalakan/mematikan fitur atau mengubah tanggal terjadwal:"
    )
    await message.answer(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

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
            "Anda memiliki 2 jenis file spreadsheet Excel yang dapat diunduh:\n\n"
            f"1️⃣ *Laporan dari File PDF Terakhir*\n"
            f"   📁 `{last_pdf['file_name']}`\n"
            f"   _File spreadsheet yang diekstrak langsung secara terpisah dari dokumen PDF Anda (tanpa menyentuh database harian)._\n\n"
            f"2️⃣ *Laporan Keuangan Harian (Database)*\n"
            f"   _Rekap transaksi pembukuan keuangan pribadi harian Anda di database bot._\n\n"
            "Silakan klik tombol di bawah untuk memilih file mana yang ingin Anda unduh:"
        )
        if isinstance(target, CallbackQuery):
            await target.message.answer(msg_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        else:
            await target.answer(msg_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        status_msg = None
        send_target = target.message if isinstance(target, CallbackQuery) else target
        try:
            status_msg = await send_target.answer("⏳ Sedang menyiapkan laporan keuangan Excel...")
            excel_path = finance.export_financial_report_excel(user_id, "all")
            await send_target.answer_document(
                FSInputFile(excel_path),
                caption=(
                    "📊 *File Laporan Keuangan Harian (Database)*\n\n"
                    "_File di atas berisi rekap transaksi keuangan harian dari database bot._\n\n"
                    "💡 *Ingin buat Excel dari file PDF lain?*\n"
                    "Cukup kirimkan file dokumen PDF (misal laporan penjualan/printing, invoice, atau mutasi bank) ke chat ini, dan Selobrow akan otomatis membuatkan file Excel khusus dari PDF tersebut tanpa mengubah database harian Anda!"
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await send_target.answer(f"Gagal membuat file Excel: {e}")
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
        f"🗑️ *BERHASIL RESET KEUANGAN*\n\n"
        f"Sebanyak {count} transaksi telah dihapus.\n"
        f"💰 *Saldo saat ini:* `Rp 0`\n"
        f"📥 *Total Pemasukan:* `Rp 0`\n"
        f"📤 *Total Pengeluaran:* `Rp 0`\n\n"
        f"_Pembukuan keuangan Anda sekarang bersih dan siap dimulai dari awal!_",
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
async def handle_callbacks(callback: CallbackQuery):
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
    elif data == "menu_notifikasi":
        user_name = callback.from_user.first_name or "Teman"
        db.register_or_update_user(user_id, user_name, callback.message.chat.id)
        settings = db.get_notification_settings(user_id)
        kb = notifications.get_notification_settings_keyboard(settings)
        sched_day = settings.get('scheduled_day', 25)
        text = (
            "🔔 *PENGATURAN NOTIFIKASI CERDAS SELOBROW*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Selobrow dapat mengirimkan rekapitulasi & laporan keuangan otomatis:\n\n"
            "• ☀️ *Daily Recap* (07:00 WIB): Rincian pengeluaran kemarin (_'Kemarin kamu keluar Rp XX.XXX'_).\n"
            "• 📅 *Weekly Recap* (Senin 07:30 WIB): Evaluasi keuangan selama 7 hari terakhir.\n"
            "• 📑 *Monthly Report* (Tanggal 1 08:00 WIB): Rekap bulanan lengkap + analisis AI + lampiran file Excel.\n"
            f"• ⏰ *Scheduled Reports* (Tanggal {sched_day} 08:30 WIB): Laporan terjadwal otomatis pada tanggal pilihan Anda.\n\n"
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
            mime_type="audio/ogg"
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
            caption=caption
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
                caption=caption
            )
        else:
            status_msg = await message.answer(
                f"⏳ Sedang membaca dan menganalisis PDF `{file_name}` untuk disusun ke spreadsheet Excel (.xlsx)...",
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
                caption=(
                    f"📊 *File Excel dari Dokumen PDF:*\n"
                    f"📁 `{file_name}`\n\n"
                    f"_File Excel ini dibuat khusus secara terpisah langsung dari isi PDF Anda tanpa mencampuri database harian._"
                ),
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )

            try:
                await status_msg.delete()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Gagal memproses dokumen: {e}", exc_info=True)
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

    # Registrasi user agar terdaftar di sistem notifikasi
    db.register_or_update_user(user_id, user_name, message.chat.id)

    reply_text = await gemini_agent.process_user_text(
        user_id=user_id,
        user_name=user_name,
        text=user_text
    )

    try:
        await message.answer(reply_text, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        # Fallback jika ada karakter format telegram yang escape
        await message.answer(reply_text)

async def main():
    db.init_db()
    logger.info("Database SQLite berhasil diinisialisasi.")
    
    if not TELEGRAM_BOT_TOKEN or len(TELEGRAM_BOT_TOKEN) < 10:
        print("\n" + "="*60)
        print("PERHATIAN: TELEGRAM_BOT_TOKEN belum disetel di file .env!")
        print("Silakan buka file 'd:\\telegram-ai-assistant\\.env' dan masukkan:")
        print("TELEGRAM_BOT_TOKEN=token_bot_anda_dari_BotFather")
        print("GEMINI_API_KEY=kunci_api_gemini_anda")
        print("="*60 + "\n")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    logger.info("Menghapus webhook lama jika ada...")
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Memulai Background Notification Scheduler (Daily/Weekly Recap, Monthly Report, Scheduled Reports)...")
    asyncio.create_task(notifications.start_notification_scheduler(bot))

    logger.info("Bot Telegram AI Selobrow siap beroperasi! Menunggu pesan...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
