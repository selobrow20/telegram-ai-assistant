import csv
import re
import difflib
import io
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

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

def search_pricelist(query: str, price_tier: str = "", brand_filter: str = "") -> Dict[str, Any]:
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
    
    # Deteksi merek dalam query jika ada (Aturan 3)
    detected_brand = brand_filter.strip().lower() if brand_filter else ""
    brands = ["hikvision", "dahua", "ruijie", "hilook", "hiview"]
    if not detected_brand:
        for b in brands:
            pattern = rf'\b{b}\b'
            if re.search(pattern, q_raw, flags=re.IGNORECASE):
                detected_brand = b
                q_raw = re.sub(pattern, '', q_raw, flags=re.IGNORECASE).strip()
                break
                
    if detected_brand:
        products = [p for p in products if p.get("Brand", "").lower() == detected_brand]
        if not products:
            return {
                "status": "not_found",
                "query": query,
                "suggestions": []
            }

    q_norm = normalize_code(q_raw)
    
    # 1. Cari exact match (persis sama setelah dinormalisasi)
    exact_matches = [p for p in products if q_norm == normalize_code(p.get("Model", ""))]
    if len(exact_matches) == 1:
        return {
            "status": "exact",
            "product": exact_matches[0],
            "price_tier": price_tier
        }
    elif len(exact_matches) > 1:
        return {
            "status": "ambiguous",
            "matches": exact_matches,
            "price_tier": price_tier
        }
    
    # 2. Coba tanpa awalan brand jika ada ('dhi', 'dh', 'ids', 'ds', 'rg', 'reyee', 'hilook', 'hiview', 'thc', 'ipc', 'th', 'hv', 'hik')
    def strip_brand_pfx(s: str) -> str:
        for pfx in ['reyee', 'dhi', 'dh', 'ids', 'ds', 'rg', 'hilook', 'hiview', 'thc', 'ipc', 'th', 'hv', 'hik']:
            if s.startswith(pfx):
                return s[len(pfx):]
        return s

    q_stripped = strip_brand_pfx(q_norm)
    pfx_matches = []
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        m_stripped = strip_brand_pfx(m_norm)
        if q_stripped == m_stripped:
            pfx_matches.append(p)
            
    if len(pfx_matches) == 1:
        return {
            "status": "exact",
            "product": pfx_matches[0],
            "price_tier": price_tier
        }
    elif len(pfx_matches) > 1:
        return {
            "status": "ambiguous",
            "matches": pfx_matches,
            "price_tier": price_tier
        }

    # 3. Cari matches awalan / substring
    substring_matches = []
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        m_stripped = strip_brand_pfx(m_norm)
        if q_norm in m_norm or (len(q_stripped) >= 3 and q_stripped in m_stripped):
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

def format_single_product_answer(product: Dict[str, Any], tier: str = "") -> str:
    """Format jawaban sesuai Aturan 7 & 8:
    Merek: ...
    Model: ...
    <tingkatan harga>: Rp ... (satu baris per tingkatan)
    Sumber: <kolom "sumber" atau "kategori" baris itu>
    """
    model = product.get("Model", "N/A")
    brand = product.get("Brand", "General")
    tier_upper = tier.upper().strip() if tier else ""
    
    price_lines = []
    brand_lower = brand.lower()
    
    if brand_lower == "hikvision":
        dpp = product.get("Harga_DPP")
        non_dpp = product.get("Harga_Non_DPP")
        msrp = product.get("Harga_MSRP")
        if tier_upper == "DPP":
            price_lines.append(f"DPP: {format_rupiah_num(dpp)}" if dpp and str(dpp) != "0" else "DPP: harga tidak tersedia")
        elif tier_upper in ("NON-DPP", "NONDPP"):
            price_lines.append(f"Non-DPP: {format_rupiah_num(non_dpp)}" if non_dpp and str(non_dpp) != "0" else "Non-DPP: harga tidak tersedia")
        elif tier_upper == "MSRP":
            price_lines.append(f"MSRP: {format_rupiah_num(msrp)}" if msrp and str(msrp) != "0" else "MSRP: harga tidak tersedia")
        else:
            if dpp and str(dpp) != "0":
                price_lines.append(f"DPP: {format_rupiah_num(dpp)}")
            if non_dpp and str(non_dpp) != "0" and non_dpp != dpp:
                price_lines.append(f"Non-DPP: {format_rupiah_num(non_dpp)}")
            if msrp and str(msrp) != "0" and msrp != dpp:
                price_lines.append(f"MSRP: {format_rupiah_num(msrp)}")
                
    elif brand_lower == "dahua":
        mdp = product.get("Harga_MDP") or product.get("Harga_MD") or product.get("Harga_ADP")
        dpp = product.get("Harga_DPP")
        msrp = product.get("Harga_MSRP")
        if tier_upper in ("MDP", "MD"):
            price_lines.append(f"MDP: {format_rupiah_num(mdp)}" if mdp and str(mdp) != "0" else "MDP: harga tidak tersedia")
        elif tier_upper == "DPP":
            price_lines.append(f"DPP: {format_rupiah_num(dpp)}" if dpp and str(dpp) != "0" else "DPP: harga tidak tersedia")
        elif tier_upper == "MSRP":
            price_lines.append(f"MSRP: {format_rupiah_num(msrp)}" if msrp and str(msrp) != "0" else "MSRP: harga tidak tersedia")
        else:
            if mdp and str(mdp) != "0":
                price_lines.append(f"MDP: {format_rupiah_num(mdp)}")
            if dpp and str(dpp) != "0" and dpp != mdp:
                price_lines.append(f"DPP: {format_rupiah_num(dpp)}")
            if msrp and str(msrp) != "0" and msrp != mdp:
                price_lines.append(f"MSRP: {format_rupiah_num(msrp)}")

    elif brand_lower == "ruijie":
        adp = product.get("Harga_ADP") or product.get("Harga_MD")
        msrp = product.get("Harga_MSRP")
        if tier_upper in ("ADP", "MD"):
            price_lines.append(f"ADP: {format_rupiah_num(adp)}" if adp and str(adp) != "0" else "ADP: harga tidak tersedia")
        elif tier_upper == "MSRP":
            price_lines.append(f"MSRP: {format_rupiah_num(msrp)}" if msrp and str(msrp) != "0" else "MSRP: harga tidak tersedia")
        else:
            if adp and str(adp) != "0":
                price_lines.append(f"ADP: {format_rupiah_num(adp)}")
            if msrp and str(msrp) != "0" and msrp != adp:
                price_lines.append(f"MSRP: {format_rupiah_num(msrp)}")

    elif brand_lower == "hilook":
        dealer = product.get("Harga_MD") or product.get("Harga_ADP")
        msrp = product.get("Harga_MSRP")
        if tier_upper in ("DEALER", "MD"):
            price_lines.append(f"Dealer: {format_rupiah_num(dealer)}" if dealer and str(dealer) != "0" else "Dealer: harga tidak tersedia")
        elif tier_upper == "MSRP":
            price_lines.append(f"MSRP: {format_rupiah_num(msrp)}" if msrp and str(msrp) != "0" else "MSRP: harga tidak tersedia")
        else:
            if dealer and str(dealer) != "0":
                price_lines.append(f"Dealer: {format_rupiah_num(dealer)}")
            if msrp and str(msrp) != "0" and msrp != dealer:
                price_lines.append(f"MSRP: {format_rupiah_num(msrp)}")

    elif brand_lower == "hiview":
        md = product.get("Harga_MD") or product.get("Harga_ADP")
        non_md = product.get("Harga_Non_DPP")
        msrp = product.get("Harga_MSRP")
        if tier_upper in ("MD", "DEALER"):
            price_lines.append(f"MD: {format_rupiah_num(md)}" if md and str(md) != "0" else "MD: harga tidak tersedia")
        elif tier_upper in ("NON-MD", "NONMD"):
            price_lines.append(f"Non-MD: {format_rupiah_num(non_md)}" if non_md and str(non_md) != "0" else "Non-MD: harga tidak tersedia")
        elif tier_upper == "MSRP":
            price_lines.append(f"MSRP: {format_rupiah_num(msrp)}" if msrp and str(msrp) != "0" else "MSRP: harga tidak tersedia")
        else:
            if md and str(md) != "0":
                price_lines.append(f"MD: {format_rupiah_num(md)}")
            if non_md and str(non_md) != "0" and non_md != md:
                price_lines.append(f"Non-MD: {format_rupiah_num(non_md)}")
            if msrp and str(msrp) != "0" and msrp != md:
                price_lines.append(f"MSRP: {format_rupiah_num(msrp)}")

    else:
        p = product.get("Harga_ADP") or product.get("Harga_MD") or product.get("Harga_DPP")
        if p and str(p) != "0":
            price_lines.append(f"Harga: {format_rupiah_num(p)}")

    if not price_lines:
        price_lines.append("Harga: harga tidak tersedia")

    sumber = product.get("Sumber") or product.get("Category") or f"{brand} Pricelist"

    lines = [
        f"Merek: {brand}",
        f"Model: {model}",
        *price_lines,
        f"Sumber: {sumber}"
    ]
    return "\n".join(lines)

def query_pricelist_tool(query: str, tier: str = "") -> str:
    """Fungsi pembantu yang dipanggil oleh Gemini Agent atau command bot.
    Mendukung pencarian 1 tipe maupun sekaligus banyak tipe.
    Mengikuti Aturan 1-11 secara konsisten.
    """
    cleaned = query.replace(";", "\n").replace(",", "\n")
    cleaned = re.sub(r'\s+(?:dan|&)\s+', '\n', cleaned, flags=re.IGNORECASE)
    parts = [p.strip() for p in cleaned.split("\n") if p.strip()]
    
    if len(parts) > 1:
        results = []
        for part in parts:
            p_clean = re.sub(r'^(?:tolong\s+)?(?:carikan\s+)?(?:harga\s+)?(?:adp\s+)?(?:md\s+)?(?:dpp\s+)?(?:dealer\s+)?(?:untuk\s+)?', '', part, flags=re.IGNORECASE).strip()
            p_clean = re.sub(r'\s+(?:berapa|dong|ya|unit|pcs)$', '', p_clean, flags=re.IGNORECASE).strip()
            if not p_clean:
                continue
            res = search_pricelist(p_clean, tier)
            st = res.get("status")
            if st == "exact":
                results.append(format_single_product_answer(res["product"], tier))
            elif st == "ambiguous":
                m_list = [format_single_product_answer(m, tier) for m in res['matches'][:4]]
                results.append(f"Ditemukan beberapa baris yang cocok untuk '{p_clean}':\n\n" + "\n\n".join(m_list) + "\n\nMana yang Anda maksud?")
            elif st == "not_found_with_suggestions" and res.get("suggestions"):
                sugs = [f"• {s}" for s in res["suggestions"]]
                results.append(f"Model {p_clean} tidak ada di pricelist.\n\nBerikut model yang mirip:\n" + "\n".join(sugs))
            else:
                results.append(f"Model {p_clean} tidak ada di pricelist.")
        return "\n\n".join(results)
    
    # 1 tipe saja
    result = search_pricelist(query, tier)
    st = result.get("status")
    
    if st == "exact":
        return format_single_product_answer(result["product"], tier)
        
    elif st == "ambiguous":
        items = result["matches"]
        lines = [f"Ditemukan beberapa baris yang cocok untuk '{query}':\n"]
        for p in items:
            lines.append(format_single_product_answer(p, tier))
        lines.append("\nMana yang Anda maksud?")
        return "\n\n".join(lines)
        
    elif st == "not_found_with_suggestions":
        sug = result.get("suggestions", [])
        if sug:
            sugs = [f"• {s}" for s in sug]
            return f"Model {query} tidak ada di pricelist.\n\nBerikut model yang mirip:\n" + "\n".join(sugs)
        return f"Model {query} tidak ada di pricelist."
        
    else:
        return f"Model {query} tidak ada di pricelist."

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

def extract_text_from_excel(doc_bytes: bytes, max_rows: int = 150) -> str:
    """Ekstrak isi teks/tabel dari file Excel (.xlsx) untuk dianalisis oleh AI."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(doc_bytes), data_only=True)
        sheets_data = []
        for name in wb.sheetnames[:5]:
            ws = wb[name]
            lines = [f"=== Sheet: {name} ==="]
            rows = list(ws.iter_rows(values_only=True))
            for r in rows[:max_rows]:
                if not any(r):
                    continue
                r_str = [str(c) if c is not None else "" for c in r]
                lines.append(" | ".join(r_str))
            if len(rows) > max_rows:
                lines.append(f"... (dan {len(rows) - max_rows} baris lainnya)")
            sheets_data.append("\n".join(lines))
        return "\n\n".join(sheets_data)
    except Exception as e:
        logger.error(f"Gagal ekstrak excel: {e}")
        return ""

def import_pricelist_from_excel(doc_bytes: bytes) -> Tuple[bool, str, int]:
    """Membaca file Excel (.xlsx) semua sheet dan menggabungkan (merge) ke data/pricelist.csv tanpa menghapus data produk yang sudah ada."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(doc_bytes), data_only=True)
        new_extracted = {}

        for sname in wb.sheetnames:
            if sname.lower() in ["update", "history", "changelog", "hot model list for retail", "hot model list for smb project"]:
                continue
            ws = wb[sname]
            rows = list(ws.iter_rows(values_only=True))
            if not rows or len(rows) < 2:
                continue

            header_idx = -1
            for idx, r in enumerate(rows[:12]):
                r_str = [str(cell or "").lower().strip() for cell in r]
                if any("model" in c or "tipe" in c or "type" in c or (c == "name" and any("price" in x or "dpp" in x for x in r_str)) for c in r_str):
                    header_idx = idx
                    break

            if header_idx == -1:
                continue

            header_row = [str(cell or "").lower().strip() for cell in rows[header_idx]]

            col_order = -1
            col_model = -1
            col_desc = -1
            col_dpp = -1
            col_adp = -1
            col_md = -1
            col_msrp = -1
            col_warranty = -1

            for i, col_name in enumerate(header_row):
                if "order" in col_name and ("model" in col_name or "name" in col_name):
                    col_order = i
                elif ("model" in col_name or "tipe" in col_name or "type" in col_name or col_name == "name") and col_model == -1:
                    col_model = i
                elif "desc" in col_name or "keterangan" in col_name or "deskripsi" in col_name or "spesifikasi" in col_name:
                    col_desc = i
                elif "dpp" in col_name:
                    col_dpp = i
                elif "adp" in col_name:
                    col_adp = i
                elif "bottom" in col_name or "md" in col_name or "dealer" in col_name:
                    col_md = i
                elif "msrp" in col_name or "srp" in col_name or "retail" in col_name:
                    col_msrp = i
                elif "warranty" in col_name or "garansi" in col_name:
                    col_warranty = i

            # Fallback untuk kolom harga jika belum ketemu
            if col_dpp == -1 and col_adp == -1 and col_md == -1:
                for i, col_name in enumerate(header_row):
                    if "price" in col_name or "harga" in col_name:
                        col_dpp = i
                        break

            def clean_num(val):
                if not val:
                    return "0"
                try:
                    if isinstance(val, (int, float)):
                        return str(int(round(val)))
                except Exception:
                    pass
                c = re.sub(r'[^0-9]', '', str(val))
                return c if c else "0"

            for r in rows[header_idx + 1:]:
                if not r:
                    continue

                raw_order = str(r[col_order]).strip() if col_order != -1 and len(r) > col_order and r[col_order] else ""
                raw_model = str(r[col_model]).strip() if col_model != -1 and len(r) > col_model and r[col_model] else ""

                candidates = []
                for rm in [raw_order, raw_model]:
                    if not rm or rm.lower() in ("none", "model", "tipe", "type", "order model", "basic model", "name"):
                        continue
                    cm = re.sub(r'[\（\(](?:hot\s*sku|project|new)[^\）\)]*[\）\)]', '', rm, flags=re.IGNORECASE).strip()
                    cm = cm.split('\n')[0].strip()
                    if len(cm) >= 3 and cm not in candidates:
                        candidates.append(cm)

                if not candidates:
                    continue

                # Ambil harga
                p_dpp = clean_num(r[col_dpp]) if col_dpp != -1 and len(r) > col_dpp else "0"
                p_adp = clean_num(r[col_adp]) if col_adp != -1 and len(r) > col_adp else p_dpp
                p_md = clean_num(r[col_md]) if col_md != -1 and len(r) > col_md else (p_dpp or p_adp)
                p_final = p_dpp if int(p_dpp) > 0 else (p_adp if int(p_adp) > 0 else p_md)

                if not p_final or int(p_final) == 0:
                    continue

                desc = str(r[col_desc]).strip() if col_desc != -1 and len(r) > col_desc and r[col_desc] else ""
                desc = desc.replace('\n', ' ')
                msrp = clean_num(r[col_msrp]) if col_msrp != -1 and len(r) > col_msrp else p_final
                warranty = str(r[col_warranty]).strip() if col_warranty != -1 and len(r) > col_warranty and r[col_warranty] else "2 Years Warranty"

                # Deteksi Brand otomatis
                brand = "General"
                first_cand = candidates[0].upper()
                file_str = str(file_path).lower()
                if "hilook" in file_str or first_cand.startswith("THC-") or first_cand.startswith("IPC-B12") or first_cand.startswith("IPC-D12") or first_cand.startswith("IPC-B14") or first_cand.startswith("IPC-D14") or first_cand.startswith("DVR-2") or first_cand.startswith("NVR-1"):
                    brand = "HiLook"
                elif "hiview" in file_str or first_cand.startswith("HV-") or first_cand.startswith("TH-") or first_cand.startswith("T1A20") or first_cand.startswith("B1A20") or first_cand.startswith("T1290") or first_cand.startswith("B1290"):
                    brand = "Hiview"
                elif first_cand.startswith("DS-") or first_cand.startswith("IDS-") or first_cand.startswith("HC-"):
                    brand = "Hikvision"
                elif first_cand.startswith("DH-") or first_cand.startswith("DHI-") or first_cand.startswith("XVR") or first_cand.startswith("NVR") or first_cand.startswith("HAC"):
                    brand = "Dahua"
                elif first_cand.startswith("RG-") or first_cand.startswith("REYEE") or "RUIJIE" in first_cand:
                    brand = "Ruijie"

                for cand in candidates:
                    new_extracted[cand] = {
                        "Model": cand,
                        "Description": desc[:150],
                        "Harga_MD": p_final,
                        "Harga_ADP": p_final,
                        "Harga_DPP": p_dpp or p_final,
                        "Harga_MSRP": msrp or p_final,
                        "Harga_Non_DPP": "",
                        "Category": sname,
                        "Sumber": f"{brand} {sname}",
                        "Warranty": warranty,
                        "Brand": brand
                    }

        if not new_extracted:
            return False, "Tidak ada data produk yang berhasil diekstrak dari seluruh sheet.", 0

        # Muat produk yang sudah ada agar tidak terhapus (Merge)
        existing = {}
        if PRICELIST_PATH.exists():
            with open(PRICELIST_PATH, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    m = r.get("Model", "").strip()
                    if m:
                        existing[m] = r

        # Gabungkan
        for m, item in new_extracted.items():
            existing[m] = item

        fieldnames = ["Model", "Description", "Harga_MD", "Harga_ADP", "Harga_DPP", "Harga_MSRP", "Harga_Non_DPP", "Category", "Sumber", "Warranty", "Brand"]
        with open(PRICELIST_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in existing.values():
                writer.writerow({k: r.get(k, "") for k in fieldnames})

        return True, f"Berhasil mengimpor {len(new_extracted)} produk ke database (Total sekarang: {len(existing)} produk).", len(new_extracted)
    except Exception as e:
        return False, f"Gagal membaca file Excel: {e}", 0

def update_product_price(model_query: str, new_price: Any) -> Tuple[bool, str]:
    """Mengubah atau memperbarui harga suatu produk di data/pricelist.csv."""
    clean_price = re.sub(r'[^0-9]', '', str(new_price))
    if not clean_price:
        return False, "Nominal harga tidak valid."

    products = load_pricelist()
    q_norm = normalize_code(model_query)

    found = False
    updated_model = ""
    for p in products:
        m_norm = normalize_code(p.get("Model", ""))
        if q_norm == m_norm or (q_norm.startswith("rg") and q_norm[2:] == m_norm[2:]) or (q_norm.startswith("dh") and q_norm[2:] == m_norm[2:]):
            p["Harga_ADP"] = clean_price
            p["Harga_MD"] = clean_price
            updated_model = p.get("Model", model_query)
            found = True
            break

    if not found:
        for p in products:
            m_norm = normalize_code(p.get("Model", ""))
            if q_norm in m_norm:
                p["Harga_ADP"] = clean_price
                p["Harga_MD"] = clean_price
                updated_model = p.get("Model", model_query)
                found = True
                break

    if not found:
        return False, f"Produk '{model_query}' tidak ditemukan di database pricelist."

    fieldnames = ["Model", "Description", "Harga_MD", "Harga_ADP", "Harga_Installer", "Harga_Online", "Harga_MSRP", "Warranty", "Brand"]
    with open(PRICELIST_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)

    return True, f"✅ Harga {updated_model} berhasil diupdate menjadi {format_rupiah_num(clean_price)}."
