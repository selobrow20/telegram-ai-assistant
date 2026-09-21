import csv
import re
import difflib
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

PRICELIST_PATH = Path("data/pricelist.csv")

def normalize_code(code: str) -> str:
    """Bersihkan kode: lowercase, hapus spasi, tanda hubung, dan tanda baca."""
    if not code:
        return ""
    cleaned = re.sub(r'[^a-zA-Z0-9]', '', code).lower()
    return cleaned

def load_pricelist() -> List[Dict[str, Any]]:
    """Muat seluruh data pricelist dari file CSV."""
    if not PRICELIST_PATH.exists():
        return []
    
    products = []
    with open(PRICELIST_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            products.append(row)
    return products

def format_rupiah_num(val: Any) -> str:
    """Format angka integer/float ke format Rupiah standar: Rp 1.250.000."""
    try:
        clean_val = re.sub(r'[^0-9]', '', str(val))
        if not clean_val:
            return "Rp 0"
        num = int(clean_val)
        return f"Rp {num:,}".replace(",", ".")
    except Exception:
        return f"Rp {val}"

def search_pricelist(query: str, price_tier: str = "MD") -> Dict[str, Any]:
    """
    Cari produk di pricelist berdasarkan kode, model, atau nama.
    Menerapkan Aturan 1, 2, 3, 4, 5.
    """
    products = load_pricelist()
    if not products:
        return {
            "status": "empty",
            "message": "Data pricelist belum tersedia di database."
        }
    
    q_raw = query.strip()
    q_norm = normalize_code(q_raw)
    
    # 1. Cari exact match (persis sama setelah dinormalisasi)
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        if q_norm == m_norm:
            return {
                "status": "exact",
                "product": p,
                "price_tier": price_tier
            }
    
    # 2. Coba tanpa awalan 'rg' jika ada (misal user cari 'ew1200g' -> 'rgew1200g')
    q_no_rg = q_norm[2:] if q_norm.startswith("rg") else q_norm
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        m_no_rg = m_norm[2:] if m_norm.startswith("rg") else m_norm
        if q_no_rg == m_no_rg:
            return {
                "status": "exact",
                "product": p,
                "price_tier": price_tier
            }

    # 3. Cari matches awalan / substring
    substring_matches = []
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        m_no_rg = m_norm[2:] if m_norm.startswith("rg") else m_norm
        if q_norm in m_norm or q_no_rg in m_no_rg:
            substring_matches.append(p)
            
    if len(substring_matches) == 1:
        return {
            "status": "exact",
            "product": substring_matches[0],
            "price_tier": price_tier
        }
    elif len(substring_matches) > 1 and len(substring_matches) <= 6:
        return {
            "status": "ambiguous",
            "matches": substring_matches,
            "price_tier": price_tier
        }
        
    # 4. Jika tidak ditemukan, gunakan similarity (difflib) untuk 3 kandidat paling mirip
    all_models = [p.get("Model", "") for p in products]
    all_norms = {normalize_code(m): m for m in all_models}
    
    close_norms = difflib.get_close_matches(q_norm, list(all_norms.keys()), n=3, cutoff=0.4)
    if not close_norms:
        # Coba juga pencarian kata kunci pada Description
        desc_matches = []
        words = [w for w in q_raw.lower().split() if len(w) > 2]
        for p in products:
            desc_lower = p.get("Description", "").lower()
            if any(w in desc_lower for w in words):
                desc_matches.append(p)
                if len(desc_matches) >= 3:
                    break
        if desc_matches:
            return {
                "status": "not_found_with_suggestions",
                "query": q_raw,
                "suggestions": [p.get("Model", "") for p in desc_matches]
            }

        return {
            "status": "not_found",
            "query": q_raw,
            "suggestions": []
        }
    
    similar_models = [all_norms[k] for k in close_norms]
    return {
        "status": "not_found_with_suggestions",
        "query": q_raw,
        "suggestions": similar_models[:3]
    }

def format_single_product_answer(product: Dict[str, Any], tier: str = "MD") -> str:
    """Format jawaban sesuai Aturan 6, 7."""
    model = product.get("Model", "N/A")
    desc = product.get("Description", "-")
    warranty = product.get("Warranty", "3 Years Warranty")
    
    tier_upper = tier.upper()
    if "MSRP" in tier_upper or "USER" in tier_upper:
        price_val = product.get("Harga_MSRP", "0")
        price_label = "MSRP"
    elif "INSTALLER" in tier_upper:
        price_val = product.get("Harga_Installer", "0")
        price_label = "Installer"
    elif "ADP" in tier_upper:
        price_val = product.get("Harga_ADP", "0")
        price_label = "ADP"
    else: # Default MD
        price_val = product.get("Harga_MD", "0")
        price_label = "MD"
        
    formatted_price = format_rupiah_num(price_val)
    
    return (
        f"Tipe: {model}\n"
        f"Harga ({price_label}): {formatted_price}\n"
        f"Keterangan: {desc} (Garansi: {warranty})"
    )

def query_pricelist_tool(query: str, tier: str = "MD") -> str:
    """Fungsi pembantu yang dipanggil oleh Gemini Agent."""
    result = search_pricelist(query, tier)
    st = result.get("status")
    
    if st == "exact":
        return format_single_product_answer(result["product"], result.get("price_tier", "MD"))
        
    elif st == "ambiguous":
        items = result["matches"]
        lines = [f"Ditemukan beberapa tipe yang mirip dengan '{query}':"]
        for p in items:
            p_price = format_rupiah_num(p.get("Harga_MD", 0))
            lines.append(f"• {p.get('Model')}: {p_price} ({p.get('Description')[:55]}...)")
        lines.append("Mana tipe yang Anda maksud?")
        return "\n".join(lines)
        
    elif st == "not_found_with_suggestions":
        sug = result.get("suggestions", [])
        if sug:
            sug_str = ", ".join(sug)
            return f"Tipe '{query}' tidak ditemukan di pricelist. Mungkin yang Anda maksud salah satu dari tipe ini: {sug_str}?"
        return f"Tipe '{query}' tidak ditemukan di pricelist."
        
    else:
        return f"Tipe '{query}' tidak ditemukan di pricelist."

def save_new_pricelist_csv(content: str) -> Tuple[bool, str, int]:
    """Menyimpan file CSV pricelist baru yang diupload user."""
    try:
        lines = [l for l in content.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            return False, "File CSV kosong atau tidak memiliki baris data.", 0
        
        header = lines[0].lower()
        if "model" not in header and "tipe" not in header:
            return False, "Format CSV harus memiliki kolom 'Model' atau 'Tipe'.", 0
            
        with open(PRICELIST_PATH, "w", encoding="utf-8") as f:
            f.write(content.strip())
            
        products = load_pricelist()
        return True, f"Pricelist berhasil diperbarui dengan {len(products)} produk.", len(products)
    except Exception as e:
        return False, f"Gagal menyimpan pricelist CSV: {e}", 0
