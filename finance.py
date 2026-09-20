from datetime import datetime
from database import get_balance, get_category_breakdown, get_transactions_by_period

def format_rupiah(amount: float) -> str:
    # Format e.g. 150000 -> Rp 150.000
    formatted = f"{int(amount):,}".replace(",", ".")
    return f"Rp {formatted}"

def generate_balance_summary(user_id: int) -> str:
    bal = get_balance(user_id)
    inc = format_rupiah(bal['total_income'])
    exp = format_rupiah(bal['total_expense'])
    sisa = format_rupiah(bal['balance'])
    
    status_icon = "🟢" if bal['balance'] >= 0 else "🔴"

    text = (
        "📊 *RINGKASAN KEUANGAN KESELURUHAN*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Total Pemasukan:* {inc}\n"
        f"💸 *Total Pengeluaran:* {exp}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{status_icon} *Sisa Saldo:* {sisa}\n\n"
        "_Tip: Ketik atau kirim voice note untuk mencatat transaksi, misal: 'Beli bensin 30rb' atau 'Dapat bonus 500k'_"
    )
    return text

def generate_financial_report(user_id: int, period: str = "month") -> str:
    period_label = {
        "today": "Hari Ini",
        "week": "7 Hari Terakhir",
        "month": "Bulan Ini",
        "all": "Semua Waktu"
    }.get(period, "Bulan Ini")

    summary = get_category_breakdown(user_id, period)
    transactions = get_transactions_by_period(user_id, period)

    tot_inc = format_rupiah(summary['total_income'])
    tot_exp = format_rupiah(summary['total_expense'])
    net = format_rupiah(summary['balance'])

    lines = [
        f"📑 *LAPORAN KEUANGAN ({period_label.upper()})*",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📥 *Total Pemasukan:* {tot_inc}",
        f"📤 *Total Pengeluaran:* {tot_exp}",
        f"💵 *Arus Kas Bersih:* {net}",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if summary['expense_categories']:
        lines.append("\n📌 *Rincian Pengeluaran per Kategori:*")
        for cat in summary['expense_categories']:
            pct = (cat['total'] / summary['total_expense'] * 100) if summary['total_expense'] > 0 else 0
            lines.append(f" • *{cat['category']}*: {format_rupiah(cat['total'])} ({pct:.1f}% - {cat['count']}x)")

    if summary['income_categories']:
        lines.append("\n💎 *Rincian Pemasukan:*")
        for cat in summary['income_categories']:
            lines.append(f" • *{cat['category']}*: {format_rupiah(cat['total'])} ({cat['count']}x)")

    if transactions:
        lines.append("\n🕒 *Transaksi Terbaru:*")
        for t in transactions[:8]:
            icon = "🟢 +" if t['type'] == 'income' else "🔴 -"
            desc = f" ({t['description']})" if t['description'] else ""
            lines.append(f"{icon} {format_rupiah(t['amount'])} _{t['category']}_{desc} [{t['date']}]")
        if len(transactions) > 8:
            lines.append(f"_...dan {len(transactions) - 8} transaksi lainnya._")
    else:
        lines.append("\n_Belum ada transaksi pada periode ini._")

    return "\n".join(lines)
