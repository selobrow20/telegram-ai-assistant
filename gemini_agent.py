import logging
from typing import Dict, Any, List
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_MODEL
import database as db
import finance
import pricelist
import notifications

logger = logging.getLogger(__name__)

# Simpan riwayat obrolan per user: {user_id: [types.Content, ...]}
user_histories: Dict[int, List[types.Content]] = {}
MAX_HISTORY = 12

def get_client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY belum disetel! Harap isi di file .env")
    return genai.Client(api_key=GEMINI_API_KEY)

def clear_user_history(user_id: int):
    user_histories.pop(user_id, None)

SYSTEM_PROMPT = """
Anda adalah asisten kerja pribadi 'Selobrow' di Telegram.
PENTING: Nama Anda adalah 'Selobrow'.

ATURAN GAYA KOMUNIKASI (SANGAT PENTING):
1. JAWAB SINGKAT, PADAT, DAN LANGSUNG KE INTI (To the point).
2. JANGAN menggunakan basa-basi pembuka yang panjang.
3. Berikan informasi yang dibutuhkan dalam format rapi dan bersih.
4. Gunakan bahasa Indonesia santai, sopan, dan jelas.

TUGAS UTAMA:
1. INFORMASI HARGA PRICELIST (SANGAT PENTING):
   Kamu adalah asisten harga. Satu-satunya sumber kebenaranmu adalah data pricelist melalui fungsi `cari_harga_pricelist`. Kamu TIDAK boleh menggunakan pengetahuan umum, ingatan, atau perkiraan untuk harga apa pun.

   ATURAN WAJIB FORMAT JAWABAN:
   1. JAWAB HANYA MODEL DAN HARGA SAJA untuk semua tipe dan merek (Hikvision, Dahua, Ruijie, HiLook, Hiview):
      <Model> : Rp <Harga>
      Contoh:
      IPC-B121HE-UC : Rp 415.200
      THC-B120-PC : Rp 214.720
      HV-T127PS : Rp 225.000
      DH-H3A : Rp 292.211
      DS-2CD1023G2-LIUF : Rp 1.131.300
      RG-EW1200G PRO : Rp 557.220
      DILARANG menambahkan kata 'Merek:', 'Sumber:', deskripsi, atau basa-basi apa pun.
   2. Jika pengguna menanyakan banyak tipe sekaligus, jawab langsung per baris:
      <Model 1> : Rp <Harga 1>
      <Model 2> : Rp <Harga 2>
      <Model 3> : Rp <Harga 3>
   3. Tingkatan harga default per merek:
      - HiLook (IP & Analog): Dealer price
      - Hiview: MD PRICE
      - Dahua: MDP
      - Ruijie: ADP-Price (Inc PPN)
      - Hikvision: DPP
   4. Setiap harga yang kamu sebut harus disalin PERSIS dari hasil fungsi `cari_harga_pricelist`. Jangan membulatkan, menghitung ulang, atau mengubah angka.
   5. Abaikan huruf besar/kecil, spasi, tanda hubung, serta awalan merek (RG-, DH-, DHI-, DS-, THC-, IPC-, HV-, TH-, dsb.).
   6. Kalau model TIDAK ada di data, jawab persis:
      "Model <nama> tidak ada di pricelist." Jika ada saran mirip dari hasil pencarian, sebutkan di bawahnya. Jangan pernah memberi harga untuk model yang tidak ada di data.
   7. Kalau kolom harga kosong, tulis "<Model> : harga tidak tersedia".
   8. Jawaban harus super ringkas dan to the point tanpa kata pengantar atau penutup.

2. PENCATATAN KEUANGAN:
   - Pengguna menyebutkan pengeluaran/pemasukan ("makan 25rb", "bensin 35k", "gaji 5jt") -> panggil `catat_transaksi_keuangan`.
   - Cek saldo atau laporan -> panggil `cek_saldo` atau `buat_laporan_keuangan`.

3. STRUK / NOTA & PDF:
   - Foto nota/struk belanja -> otomatis baca merchant & total, lalu catat pengeluaran.
   - Dokumen PDF -> sistem otomatis mengonversi ke file Excel terpisah tanpa mengubah database harian.

4. TO-DO & CATATAN:
   - Tambah to-do (`tambah_tugas_harian`), selesai (`selesaikan_tugas`), lihat (`lihat_daftar_tugas`).
   - Simpan memo (`simpan_catatan`), lihat memo (`lihat_catatan`).

5. NOTIFIKASI CERDAS & JADWAL:
   - Cek status notifikasi -> panggil `cek_status_notifikasi`.
   - Mengubah preferensi -> panggil `atur_notifikasi_cerdas`.
   - Kirim preview / tes notifikasi sekarang -> panggil `kirim_tes_notifikasi`.
   - PENTING: Semua notifikasi cerdas (Daily Recap 07:00 WIB, Weekly Recap Senin 07:30 WIB, Monthly Report Tgl 1 08:00 WIB, Scheduled Report Tgl 25 08:30 WIB) SECARA DEFAULT SUDAH AKTIF dan berjalan di latar belakang. JANGAN PERNAH berasumsi atau mengatakan "notifikasi belum aktif" tanpa memanggil `cek_status_notifikasi`!
"""

def create_tools_for_user(user_id: int, user_name: str = "Teman"):
    def catat_transaksi_keuangan(tipe: str, nominal: float, kategori: str, keterangan: str = "") -> str:
        """Mencatat pemasukan atau pengeluaran keuangan ke database.
        Args:
            tipe: 'pengeluaran' atau 'pemasukan'
            nominal: Jumlah uang dalam angka Rupiah (misal 50000)
            kategori: Kategori transaksi (misal: Makanan, Transportasi, Belanja, Tagihan, Gaji, dll)
            keterangan: Rincian transaksi (misal: 'Nasi goreng dan es teh')
        """
        t_type = "income" if "masuk" in tipe.lower() or "income" in tipe.lower() else "expense"
        trans_id = db.add_transaction(user_id, t_type, nominal, kategori, keterangan)
        bal = db.get_balance(user_id)
        fmt_nominal = finance.format_rupiah(nominal)
        fmt_saldo = finance.format_rupiah(bal['balance'])
        jenis_str = "Pemasukan" if t_type == "income" else "Pengeluaran"
        desc_str = f" - {keterangan}" if keterangan else ""
        return f"✅ {jenis_str} {fmt_nominal} ({kategori}{desc_str})\n💰 Sisa Saldo: {fmt_saldo}"


    def cek_saldo() -> str:
        """Mengecek ringkasan saldo keuangan pengguna saat ini (total pemasukan, pengeluaran, dan saldo bersih)."""
        return finance.generate_balance_summary(user_id)

    def buat_laporan_keuangan(periode: str = "month") -> str:
        """Membuat laporan keuangan lengkap berdasarkan periode.
        Args:
            periode: Pilihan periode ('today' untuk hari ini, 'week' untuk minggu ini, 'month' untuk bulan ini, 'all' untuk semua waktu)
        """
        return finance.generate_financial_report(user_id, periode)

    def tambah_tugas_harian(judul_tugas: str, batas_waktu: str = "") -> str:
        """Menambahkan tugas baru atau to-do list harian pengguna.
        Args:
            judul_tugas: Deskripsi tugas/kegiatan yang harus dilakukan
            batas_waktu: Waktu atau tanggal deadline (opsional, contoh: 'Besok jam 9 pagi')
        """
        task_id = db.add_task(user_id, judul_tugas, batas_waktu if batas_waktu else None)
        return f"Tugas berhasil disimpan dengan ID #{task_id}: '{judul_tugas}'" + (f" (Deadline: {batas_waktu})" if batas_waktu else "")

    def lihat_daftar_tugas(status: str = "pending") -> str:
        """Melihat daftar tugas / to-do list.
        Args:
            status: 'pending' untuk tugas yang belum selesai, 'completed' untuk yang sudah selesai, atau 'all' untuk semua
        """
        st = None if status == "all" else status
        tasks = db.get_tasks(user_id, st)
        if not tasks:
            return "Tidak ada tugas dalam daftar saat ini. Semua beres!"
        res = "Daftar Tugas:\n"
        for t in tasks:
            icon = "✅" if t['status'] == 'completed' else "⏳"
            dl = f" (Deadline: {t['due_date']})" if t['due_date'] else ""
            res += f"- [#{t['id']}] {icon} {t['title']}{dl}\n"
        return res

    def selesaikan_tugas(task_id: int) -> str:
        """Menandai suatu tugas sebagai telah selesai berdasarkan ID tugas.
        Args:
            task_id: Angka ID tugas
        """
        ok = db.update_task_status(user_id, task_id, "completed")
        if ok:
            return f"Hebat! Tugas #{task_id} berhasil ditandai selesai."
        return f"Tugas dengan ID #{task_id} tidak ditemukan."

    def simpan_catatan(judul: str, isi_catatan: str) -> str:
        """Menyimpan memo atau catatan harian bebas.
        Args:
            judul: Judul memo/catatan
            isi_catatan: Isi lengkap teks catatan
        """
        nid = db.add_note(user_id, isi_catatan, judul)
        return f"Catatan '{judul}' berhasil disimpan dengan ID #{nid}."

    def lihat_catatan() -> str:
        """Melihat catatan atau memo harian yang pernah disimpan."""
        notes = db.get_notes(user_id, limit=10)
        if not notes:
            return "Belum ada catatan yang tersimpan."
        res = "Catatan Tersimpan:\n"
        for n in notes:
            t = f"*{n['title']}*: " if n['title'] else ""
            res += f"- [#{n['id']}] {t}{n['content']} ({n['created_at'][:10]})\n"
        return res

    def catat_banyak_transaksi(daftar_transaksi: list) -> str:
        """Mencatat banyak transaksi keuangan sekaligus ke database (berguna saat membaca tabel PDF laporan, mutasi, atau rekap penjualan).
        Args:
            daftar_transaksi: List of dicts, masing-masing memuat 'type' ('pemasukan'/'pengeluaran'), 'amount' (angka rupiah), 'category' (kategori), dan 'description' (keterangan).
        """
        count = db.add_multiple_transactions(user_id, daftar_transaksi)
        bal = db.get_balance(user_id)
        return f"Berhasil menyimpan {count} transaksi ke database. Total Pemasukan: {finance.format_rupiah(bal['total_income'])}, Total Pengeluaran: {finance.format_rupiah(bal['total_expense'])}, Saldo: {finance.format_rupiah(bal['balance'])}."

    def reset_keuangan() -> str:
        """Mereset saldo dan menghapus seluruh riwayat transaksi keuangan pengguna agar mulai dari Rp 0 kembali."""
        count = db.reset_user_finances(user_id)
        return f"Saldo dan seluruh riwayat transaksi ({count} transaksi) berhasil di-reset menjadi Rp 0. Pembukuan keuangan Anda sekarang bersih dan siap dimulai dari awal!"

    def atur_notifikasi_cerdas(jenis_notifikasi: str, status: bool, tanggal: int = 0) -> str:
        """Mengatur preferensi notifikasi cerdas pengguna (Daily Recap, Weekly Recap, Monthly Report, atau Scheduled Reports).
        Args:
            jenis_notifikasi: 'daily' (harian pagi), 'weekly' (mingguan Senin), 'monthly' (bulanan + AI), 'scheduled' (terjadwal tgl tertentu), atau 'all'
            status: True untuk mengaktifkan, False untuk mematikan
            tanggal: Tanggal 1-31 untuk laporan terjadwal (opsional)
        """
        val = 1 if status else 0
        res_msgs = []
        j = str(jenis_notifikasi).lower()
        if "daily" in j or "harian" in j:
            db.update_notification_setting(user_id, "daily_recap_enabled", val)
            res_msgs.append(f"Rekap Harian (07:00 WIB) telah {'diaktifkan ✅' if status else 'dinonaktifkan ❌'}")
        if "weekly" in j or "mingguan" in j:
            db.update_notification_setting(user_id, "weekly_recap_enabled", val)
            res_msgs.append(f"Rekap Mingguan (Senin 07:30 WIB) telah {'diaktifkan ✅' if status else 'dinonaktifkan ❌'}")
        if "monthly" in j or "bulanan" in j:
            db.update_notification_setting(user_id, "monthly_report_enabled", val)
            res_msgs.append(f"Laporan Bulanan + Analisis AI telah {'diaktifkan ✅' if status else 'dinonaktifkan ❌'}")
        if "sched" in j or "jadwal" in j or "tanggal" in j:
            db.update_notification_setting(user_id, "scheduled_reports_enabled", val)
            if 1 <= tanggal <= 31:
                db.update_notification_setting(user_id, "scheduled_day", tanggal)
                res_msgs.append(f"Laporan Terjadwal telah {'diaktifkan ✅' if status else 'dinonaktifkan ❌'} setiap tanggal {tanggal}")
            else:
                res_msgs.append(f"Laporan Terjadwal telah {'diaktifkan ✅' if status else 'dinonaktifkan ❌'}")
        if not res_msgs:
            db.update_notification_setting(user_id, "daily_recap_enabled", val)
            db.update_notification_setting(user_id, "weekly_recap_enabled", val)
            db.update_notification_setting(user_id, "monthly_report_enabled", val)
            db.update_notification_setting(user_id, "scheduled_reports_enabled", val)
            res_msgs.append(f"Semua Notifikasi Cerdas telah {'diaktifkan ✅' if status else 'dinonaktifkan ❌'}")
        return "Pengaturan Notifikasi Cerdas berhasil diperbarui:\n" + "\n".join(f"• {m}" for m in res_msgs)

    def cek_status_notifikasi() -> str:
        """Mengecek status terkini seluruh notifikasi cerdas pengguna (apakah aktif, jam kirim, dan tanggal laporan terjadwal)."""
        s = db.get_notification_settings(user_id)
        daily = f"Aktif (Setiap hari {s.get('daily_recap_time', '07:00')} WIB)" if s.get('daily_recap_enabled') else "Nonaktif"
        weekly = "Aktif (Setiap Senin 07:30 WIB)" if s.get('weekly_recap_enabled') else "Nonaktif"
        monthly = "Aktif (Setiap Tanggal 1 08:00 WIB + AI & Excel)" if s.get('monthly_report_enabled') else "Nonaktif"
        sched = f"Aktif (Setiap Tanggal {s.get('scheduled_day', 25)} 08:30 WIB)" if s.get('scheduled_reports_enabled') else "Nonaktif"
        
        return (
            "🔔 Status Notifikasi Cerdas Anda:\n"
            f"• ☀️ Rekap Harian: {daily}\n"
            f"• 📅 Rekap Mingguan: {weekly}\n"
            f"• 📑 Laporan Bulanan AI: {monthly}\n"
            f"• ⏰ Laporan Terjadwal: {sched}\n\n"
            "Semua jadwal notifikasi aktif secara otomatis. Pengguna bisa mengubah preferensi atau meminta 'tes notifikasi' kapan saja."
        )

    def kirim_tes_notifikasi(jenis: str = "daily") -> str:
        """Mengirimkan preview atau contoh pesan notifikasi rekap keuangan saat ini untuk memastikan fitur notifikasi berjalan dengan baik.
        Gunakan jika pengguna menanyakan tes notifikasi, preview notifikasi, atau ingin melihat contoh rekapan sekarang.
        Args:
            jenis: 'daily' (rekap harian), 'weekly' (rekap mingguan), 'monthly' (laporan bulanan), atau 'scheduled' (laporan terjadwal)
        """
        j = jenis.lower()
        if "week" in j or "minggu" in j:
            return notifications.build_weekly_recap_message(user_id, user_name)
        elif "month" in j or "bulan" in j:
            summary = db.get_previous_month_summary(user_id)
            bal = db.get_balance(user_id)
            return (
                f"📊 Laporan Bulanan (Preview)\n"
                f"• Pemasukan: {finance.format_rupiah(summary['total_income'])}\n"
                f"• Pengeluaran: {finance.format_rupiah(summary['total_expense'])}\n"
                f"• Saldo Kas: {finance.format_rupiah(bal['balance'])}\n"
                f"💡 Jadwal pengiriman otomatis: Setiap tanggal 1 pukul 08:00 WIB disertai lampiran file Excel."
            )
        elif "sched" in j or "jadwal" in j or "tanggal" in j:
            s = db.get_notification_settings(user_id)
            day = s.get('scheduled_day', 25)
            return notifications.build_scheduled_report_message(user_id, user_name, day)
        else:
            return notifications.build_daily_recap_message(user_id, user_name)

    def cari_harga_pricelist(kode_atau_nama_produk: str, jenis_harga: str = "ADP") -> str:
        """Mencari harga produk di database pricelist berdasarkan kode, model, atau nama.
        Gunakan fungsi ini jika pengguna menyebut tipe/kode produk atau menanyakan harga.
        Standar harga untuk semua barang Ruijie adalah ADP-Price (IDR) Inc PPN.
        Args:
            kode_atau_nama_produk: Tipe, kode, atau nama produk (contoh: 'EW1200G', 'RG-RAP62', 'RG-ES205GC')
            jenis_harga: 'ADP' (default ADP-Price Inc PPN)
        """
        return pricelist.query_pricelist_tool(kode_atau_nama_produk, jenis_harga)

    def update_harga_produk(model_produk: str, harga_baru: float) -> str:
        """Memperbarui atau mengubah harga suatu produk di database pricelist.
        Gunakan fungsi ini jika pengguna meminta update/ubah/ganti harga produk tertentu.
        Args:
            model_produk: Tipe/kode produk yang ingin diubah (contoh: 'DH-IPC-B1E20-A')
            harga_baru: Angka nominal harga baru dalam rupiah (contoh: 399000)
        """
        ok, msg = pricelist.update_product_price(model_produk, harga_baru)
        return msg

    return [
        cari_harga_pricelist,
        update_harga_produk,
        catat_transaksi_keuangan,
        catat_banyak_transaksi,
        cek_saldo,
        buat_laporan_keuangan,
        reset_keuangan,
        cek_status_notifikasi,
        atur_notifikasi_cerdas,
        kirim_tes_notifikasi,
        tambah_tugas_harian,
        lihat_daftar_tugas,
        selesaikan_tugas,
        simpan_catatan,
        lihat_catatan
    ]


def generate_with_fallback(client: genai.Client, contents: list, config: types.GenerateContentConfig):
    models = [
        "gemini-3.1-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash-lite",
        "gemini-flash-latest",
        "gemini-3.5-flash"
    ]
    last_error = None
    for m in models:
        try:
            return client.models.generate_content(
                model=m,
                contents=contents,
                config=config
            )
        except Exception as err:
            last_error = err
            err_msg = str(err)
            logger.warning(f"Model {m} kendala: {err_msg[:80]}. Mencoba model cadangan...")
            if any(k in err_msg for k in ["429", "RESOURCE_EXHAUSTED", "503", "NOT_FOUND", "404"]):
                continue
            raise err
    raise last_error

def format_friendly_error(e: Exception) -> str:
    err = str(e)
    if "429" in err or "RESOURCE_EXHAUSTED" in err:
        return "⚡ *Batas Kecepatan Tercapai (Rate Limit)*\n\nGoogle Gemini membatasi kecepatan permintaan akun gratis per menit. Mohon tunggu sekitar **5–10 detik** lalu kirim kembali pesan Anda ya!"
    elif "503" in err or "UNAVAILABLE" in err:
        return "⏳ *Server AI Sedang Sibuk*\n\nServer Google sedang mengalami lonjakan antrean. Mohon tunggu sebentar lalu coba lagi."
    return f"Maaf, terjadi kendala saat memproses: {err[:140]}"

async def process_user_text(user_id: int, user_name: str, text: str) -> str:
    try:
        client = get_client()
        tools = create_tools_for_user(user_id, user_name)
        
        history = user_histories.setdefault(user_id, [])
        user_content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=f"[User: {user_name}]\n{text}")]
        )
        
        # Build contents payload
        contents = list(history) + [user_content]

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
            temperature=0.7
        )

        response = generate_with_fallback(client, contents, config)

        reply_text = response.text or "Baik, sudah diproses!"

        # Update user history
        model_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=reply_text)]
        )
        history.append(user_content)
        history.append(model_content)

        if len(history) > MAX_HISTORY:
            user_histories[user_id] = history[-MAX_HISTORY:]

        return reply_text
    except Exception as e:
        logger.error(f"Error in process_user_text: {e}", exc_info=True)
        return format_friendly_error(e)

async def process_user_voice(user_id: int, user_name: str, voice_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    try:
        client = get_client()
        tools = create_tools_for_user(user_id, user_name)
        
        audio_part = types.Part.from_bytes(data=voice_bytes, mime_type=mime_type)
        instruction_part = types.Part.from_text(
            text=f"[User: {user_name} mengirim pesan suara]. Dengarkan pesan suara ini secara saksama, pahami maksudnya, jalankan alat/fungsi jika ada transaksi/tugas/catatan, lalu berikan jawaban yang ramah dan relevan."
        )

        history = user_histories.setdefault(user_id, [])
        user_content = types.Content(
            role="user",
            parts=[audio_part, instruction_part]
        )
        contents = list(history) + [user_content]

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
            temperature=0.7
        )

        response = generate_with_fallback(client, contents, config)

        reply_text = response.text or "Pesan suara Anda telah saya dengarkan dan saya proses."

        model_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=reply_text)]
        )
        history.append(user_content)
        history.append(model_content)

        if len(history) > MAX_HISTORY:
            user_histories[user_id] = history[-MAX_HISTORY:]

        return reply_text
    except Exception as e:
        logger.error(f"Error in process_user_voice: {e}", exc_info=True)
        return format_friendly_error(e)

async def process_user_image(user_id: int, user_name: str, image_bytes: bytes, mime_type: str = "image/jpeg", caption: str = "") -> str:
    try:
        client = get_client()
        tools = create_tools_for_user(user_id, user_name)

        prompt_text = (
            f"[User: {user_name} mengirim foto/gambar]. Caption pengguna: '{caption if caption else 'Tidak ada'}'\n"
            "Analisis gambar tersebut secara teliti.\n"
            "JIKA GAMBAR ADALAH STRUK BELANJA, NOTA, KWITANSI, ATAU TIKET:\n"
            "1. Identifikasi nama toko/merchant (misal: Indomaret, Alfamart, SPBU, Cafe, Resto, dll).\n"
            "2. Identifikasi tanggal & jam jika ada.\n"
            "3. Rinci barang/item yang dibeli beserta harganya.\n"
            "4. Cari JUMLAH TOTAL AKHIR (Grand Total) pembayaran.\n"
            "5. WAJIB PANGGIL fungsi `catat_transaksi_keuangan` untuk mencatat nominal total tersebut sebagai pengeluaran dengan kategori yang sesuai (misal: Makanan, Belanja, Transportasi, Kesehatan, dsb).\n"
            "6. Berikan balasan yang rapi dan terstruktur: Nama Merchant, Tanggal, Rincian Barang, Total Nominal, dan konfirmasi bahwa transaksi sudah berhasil dicatat otomatis.\n"
            "JIKA GAMBAR LAIN (Grafik/Foto/Teks): Jelaskan isi gambar dan jawab sesuai caption/pertanyaan pengguna."
        )

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        instruction_part = types.Part.from_text(text=prompt_text)

        history = user_histories.setdefault(user_id, [])
        user_content = types.Content(
            role="user",
            parts=[image_part, instruction_part]
        )
        contents = list(history) + [user_content]

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
            temperature=0.4
        )

        response = generate_with_fallback(client, contents, config)

        reply_text = response.text or "Foto berhasil dianalisis."

        model_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=reply_text)]
        )
        history.append(user_content)
        history.append(model_content)

        if len(history) > MAX_HISTORY:
            user_histories[user_id] = history[-MAX_HISTORY:]

        return reply_text
    except Exception as e:
        logger.error(f"Error in process_user_image: {e}", exc_info=True)
        return format_friendly_error(e)

async def process_user_document(user_id: int, user_name: str, doc_bytes: bytes, file_name: str, mime_type: str = "application/pdf", caption: str = "") -> str:
    try:
        client = get_client()
        tools = create_tools_for_user(user_id, user_name)

        # Ekstraksi teks digital dari PDF menggunakan pypdf
        extracted_text = ""
        try:
            import pypdf
            import io
            reader = pypdf.PdfReader(io.BytesIO(doc_bytes))
            pages = []
            for i, page in enumerate(reader.pages):
                txt = page.extract_text() or ""
                if txt.strip():
                    pages.append(f"[Halaman {i+1}]:\n{txt.strip()}")
            if pages:
                extracted_text = "\n\n".join(pages)
        except Exception as pe:
            logger.warning(f"Ekstraksi teks pypdf: {pe}")

        prompt_text = (
            f"[User: {user_name} mengirim file dokumen: {file_name}]. Caption: '{caption if caption else 'Analisis dan masukkan ke pembukuan'}'\n"
            "Analisis dokumen PDF ini secara mendalam:\n"
            "1. Pahami isi utama laporan, omzet penjualan, mutasi rekening, invoice, atau laporan keuangan di dalamnya.\n"
            "2. Berikan ringkasan eksekutif yang jelas dan terstruktur dalam format bullet points rapi (Omzet/Pendapatan, Pengeluaran, Laba Bersih, Catatan Operasional).\n"
            "3. PENTING & WAJIB: Jika dokumen PDF memuat ringkasan keuangan (seperti Total Omzet/Pemasukan dan Total Pengeluaran/Modal) atau rincian transaksi, SEGERA PANGGIL fungsi `catat_transaksi_keuangan` atau `catat_banyak_transaksi` untuk LANGSUNG MEMASUKKAN angka-angka tersebut ke database pembukuan keuangan!\n"
            "   - Contoh: Catat Total Uang Masuk sebagai 'pemasukan' kategori 'Penjualan' (misal dari Shopee/Klien), dan Total Uang Keluar sebagai 'pengeluaran' kategori 'Operasional'.\n"
            "4. Informasikan ke pengguna bahwa data omzet dan pengeluaran dari PDF tersebut SUDAH BERHASIL TERCATAT ke database dan otomatis langsung masuk ke file spreadsheet Excel (.xlsx) saat mengetik /excel."
        )

        if extracted_text:
            prompt_text += f"\n\nTEKS ISI DOKUMEN:\n{extracted_text[:15000]}"

        parts = [types.Part.from_text(text=prompt_text)]
        try:
            parts.append(types.Part.from_bytes(data=doc_bytes, mime_type=mime_type))
        except Exception:
            pass

        history = user_histories.setdefault(user_id, [])
        user_content = types.Content(
            role="user",
            parts=parts
        )
        contents = list(history) + [user_content]

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=tools,
            temperature=0.4
        )

        response = generate_with_fallback(client, contents, config)

        reply_text = response.text or "Dokumen PDF telah berhasil dianalisis."

        model_content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=reply_text)]
        )
        history.append(user_content)
        history.append(model_content)

        if len(history) > MAX_HISTORY:
            user_histories[user_id] = history[-MAX_HISTORY:]

        return reply_text
    except Exception as e:
        logger.error(f"Error in process_user_document: {e}", exc_info=True)
        return format_friendly_error(e)

