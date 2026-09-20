# 🤖 Asisten AI Telegram Harian (Aria)

Asisten AI pribadi cerdas di Telegram yang mampu berinteraksi dua arah melalui **chat teks** maupun **pesan suara (voice note)**, mencatat pemasukan & pengeluaran keuangan otomatis, membuat laporan keuangan berkala, serta membantu produktivitas harian Anda (to-do list, catatan penting, dan Q&A).

---

## ✨ Fitur Unggulan

1. **🎙️ Interaksi Dua Arah (Teks & Suara / Voice Note)**
   - Anda dapat mengetik atau langsung merekam pesan suara (*voice note*) di Telegram.
   - Suara Anda diproses secara akurat oleh Google Gemini Multimodal.
   - Bot merespons kembali dengan teks rapi serta **audio pesan suara alami** menggunakan suara sintetis Microsoft Edge TTS Bahasa Indonesia (id-ID-GadisNeural / id-ID-ArdiNeural).

2. **💰 Pengelolaan Keuangan Otomatis (Personal Finance)**
   - **Pencatatan Cerdas**: Cukup ketik atau ucapkan pengeluaran/pemasukan dengan bahasa sehari-hari:
     - *'Makan siang nasi padang 25rb'*
     - *'Beli bensin motor 30.000'*
     - *'Dapet transferan gaji 6.500.000'*
     - *'Bayar tagihan listrik 180k'*
   - **Cek Saldo Real-Time**: Ketik /keuangan atau tekan tombol **Cek Saldo** untuk melihat total pemasukan, pengeluaran, dan saldo saat ini.
   - **Laporan Berkala**: Ketik /laporan untuk melihat laporan keuangan harian, mingguan, atau bulanan lengkap dengan persentase per kategori (Makanan, Transportasi, Belanja, dll).

3. **📋 Asisten Produktivitas & To-Do List**
   - *'Catat to-do: servis motor hari sabtu'*
   - *'Ingatkan besok jam 10 pagi zoom meeting'*
   - Ketik /tugas untuk melihat daftar tugas yang belum selesai.
   - *'Tandai tugas #1 sudah selesai'*.

4. **📝 Catatan & Memo Harian**
   - Simpan informasi penting kapan saja: *'Catat: nomor rekening BCA 123456789 a/n Budi'*.
   - Ketik /catatan untuk meninjau memo yang tersimpan.

5. **🧠 Tanya Jawab & Konsultasi Sehari-hari**
   - Draf pesan WhatsApp sopan, ide masakan harian, tips menghemat uang, ringkasan teks panjang, konsultasi ide, dll.

---

## 🚀 Panduan Pengaturan & Menjalankan Bot

### Langkah 1: Buat Bot Telegram & Dapatkan Token
1. Buka aplikasi Telegram dan cari **@BotFather** (dengan centang biru resmi).
2. Kirim pesan /newbot.
3. Beri nama bot Anda (misal: Asisten Aria) dan username bot yang berakhiran ot (misal: ria_asistenku_bot).
4. BotFather akan memberikan **HTTP API Token** (contoh: 7123456789:AAH...). Salin token tersebut.

### Langkah 2: Dapatkan Kunci API Google Gemini (Gratis)
1. Kunjungi situs resmi: https://aistudio.google.com/
2. Masuk dengan akun Google Anda.
3. Klik tombol **Get API key** lalu klik **Create API key**.
4. Salin kunci API yang dibuat.

### Langkah 3: Konfigurasi File .env
1. Buka folder d:\telegram-ai-assistant\
2. Buka file .env dengan Notepad atau editor teks.
3. Masukkan token dan kunci API yang sudah didapat:
   TELEGRAM_BOT_TOKEN=masukkan_token_dari_botfather_disini
   GEMINI_API_KEY=masukkan_gemini_api_key_disini
   GEMINI_MODEL=gemini-2.5-flash
   VOICE_REPLY_ENABLED=true
   TTS_VOICE=id-ID-GadisNeural
4. Simpan file tersebut.

### Langkah 4: Jalankan Bot
Cukup klik ganda (double-click) berkas:

un.bat

Atau melalui terminal:
`ash
cd d:\telegram-ai-assistant
.\.venv\Scripts\python.exe bot.py
`

Setelah muncul tulisan:
Bot Telegram AI Aria siap beroperasi! Menunggu pesan...

Buka bot Anda di Telegram dan klik tombol **Start** atau kirim pesan /start!

---

## 📂 Struktur Berkas Proyek

- ot.py: Handler Telegram bot utama (teks, suara, tombol interaktif)
- gemini_agent.py: Integrasi AI Gemini (multimodal audio, function calling tools)
- database.py: Database SQLite untuk transaksi, tugas to-do, dan memo
- inance.py: Logika perhitungan saldo, kategori & generator laporan
- 	ts.py: Sintesis suara Text-To-Speech bahasa Indonesia
- config.py: Pembaca variabel konfigurasi lingkungan (.env)
- 
equirements.txt: Daftar dependensi pustaka Python
- 
un.bat: Script peluncur 1-klik untuk Windows
- .env: File konfigurasi aktif Anda
- data/: Folder penyimpanan database SQLite dan cache audio
