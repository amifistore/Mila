import os, json, uuid, base64, logging, sqlite3, time, threading, random, re
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode, InputMediaPhoto
)
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, ConversationHandler, CallbackContext,
)
import requests
from flask import Flask, request, jsonify

# Load configuration
try:
    with open("config.json") as f:
        cfg = json.load(f)
except FileNotFoundError:
    print("Error: File config.json tidak ditemukan. Pastikan file ada di direktori yang sama.")
    exit(1)
except json.JSONDecodeError as e:
    print(f"Error: Format JSON di config.json salah. Detail: {e}")
    exit(1)
    
TOKEN = cfg["TOKEN"]
ADMIN_IDS = [int(i) for i in cfg["ADMIN_IDS"]]
BASE_URL = cfg["BASE_URL"]
API_KEY = cfg["API_KEY"]
QRIS_STATIS = cfg["QRIS_STATIS"]
WEBHOOK_URL = cfg["WEBHOOK_URL"]
WEBHOOK_PORT = cfg["WEBHOOK_PORT"]
LOG_FILE = 'bot_error.log'

# Setup logging
logging.basicConfig(
    filename=LOG_FILE, 
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cache untuk data produk
produk_cache = {
    "data": [],
    "last_updated": 0,
    "update_in_progress": False
}

CACHE_DURATION = 300  # 5 menit

# Database setup
DBNAME = "botdata.db"
def get_conn(): 
    return sqlite3.connect(DBNAME, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT, nama TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS saldo (
        user_id INTEGER PRIMARY KEY, saldo INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS riwayat_transaksi (
        id TEXT PRIMARY KEY, user_id INTEGER, produk TEXT, tujuan TEXT, harga INTEGER, waktu TEXT, status_text TEXT, keterangan TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS topup_pending (
        id TEXT PRIMARY KEY, user_id INTEGER, username TEXT, nama TEXT, nominal INTEGER, waktu TEXT, status TEXT, bukti_file_id TEXT, bukti_caption TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS produk_admin (
        kode TEXT PRIMARY KEY, harga INTEGER, deskripsi TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS kode_unik_topup (
        kode TEXT PRIMARY KEY, 
        user_id INTEGER, 
        nominal INTEGER, 
        digunakan INTEGER DEFAULT 0,
        dibuat_pada TEXT,
        digunakan_pada TEXT
    )""")
    conn.commit()
    conn.close()

# Database functions
def tambah_user(user_id, username, nama):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (id, username, nama) VALUES (?, ?, ?)", (user_id, username, nama))
    c.execute("INSERT OR IGNORE INTO saldo (user_id, saldo) VALUES (?, 0)", (user_id,))
    conn.commit()
    conn.close()

def get_saldo(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT saldo FROM saldo WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def tambah_saldo(user_id, amount):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO saldo(user_id, saldo) VALUES (?,0)", (user_id,))
    c.execute("UPDATE saldo SET saldo=saldo+? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def kurang_saldo(user_id, amount):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE saldo SET saldo=saldo-? WHERE user_id=?", (amount, user_id))
    conn.commit()
    conn.close()

def get_riwayat_user(user_id, limit=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT * FROM riwayat_transaksi WHERE user_id=? ORDER BY waktu DESC LIMIT ?""", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_riwayat(limit=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT * FROM riwayat_transaksi ORDER BY waktu DESC LIMIT ?""", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def log_riwayat(id, user_id, produk, tujuan, harga, waktu, status_text, keterangan):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO riwayat_transaksi
        (id, user_id, produk, tujuan, harga, waktu, status_text, keterangan)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, user_id, produk, tujuan, harga, waktu, status_text, keterangan))
    conn.commit()
    conn.close()

def update_riwayat_status(reffid, status_text, keterangan):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE riwayat_transaksi SET status_text=?, keterangan=? WHERE id=?",
              (status_text, keterangan, reffid))
    conn.commit()
    conn.close()

def get_riwayat_by_refid(reffid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM riwayat_transaksi WHERE id=?", (reffid,))
    row = c.fetchone()
    conn.close()
    return row

def get_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, nama FROM users WHERE id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def get_all_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, nama FROM users")
    users = c.fetchall()
    conn.close()
    return users

def get_riwayat_jml(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM riwayat_transaksi WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def insert_topup_pending(id, user_id, username, nama, nominal, waktu, status):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO topup_pending
        (id, user_id, username, nama, nominal, waktu, status, bukti_file_id, bukti_caption)
        VALUES (?, ?, ?, ?, ?, ?, ?, '', '')""",
        (id, user_id, username, nama, nominal, waktu, status))
    conn.commit()
    conn.close()

def update_topup_bukti(id, bukti_file_id, bukti_caption):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE topup_pending SET bukti_file_id=?, bukti_caption=? WHERE id=?",
              (bukti_file_id, bukti_caption, id))
    conn.commit()
    conn.close()

def update_topup_status(id, status):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE topup_pending SET status=? WHERE id=?", (status, id))
    conn.commit()
    conn.close()

def get_topup_pending_by_user(user_id, limit=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT * FROM topup_pending WHERE user_id=? ORDER BY waktu DESC LIMIT ?""", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def get_topup_pending_all(limit=10):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT * FROM topup_pending WHERE status='pending' ORDER BY waktu DESC LIMIT ?""", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_topup_by_id(id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM topup_pending WHERE id=?", (id,))
    row = c.fetchone()
    conn.close()
    return row

def get_produk_admin(kode):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT harga, deskripsi FROM produk_admin WHERE kode=?", (kode,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"harga": row[0], "deskripsi": row[1]}
    return None

def set_produk_admin_harga(kode, harga):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO produk_admin (kode, harga, deskripsi) VALUES (?, ?, '')", (kode, harga))
    c.execute("UPDATE produk_admin SET harga=? WHERE kode=?", (harga, kode))
    conn.commit()
    conn.close()

def set_produk_admin_deskripsi(kode, deskripsi):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO produk_admin (kode, harga, deskripsi) VALUES (?, 0, ?)", (kode, deskripsi))
    c.execute("UPDATE produk_admin SET deskripsi=? WHERE kode=?", (deskripsi, kode))
    conn.commit()
    conn.close()

def get_all_produk_admin():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT kode, harga, deskripsi FROM produk_admin")
    rows = c.fetchall()
    conn.close()
    
    produk_dict = {}
    for row in rows:
        produk_dict[row[0]] = {"harga": row[1], "deskripsi": row[2]}
    return produk_dict

# Fungsi untuk kode unik top up
def generate_kode_unik():
    return str(random.randint(100, 999))

def simpan_kode_unik(kode, user_id, nominal):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""INSERT INTO kode_unik_topup 
        (kode, user_id, nominal, digunakan, dibuat_pada) 
        VALUES (?, ?, ?, 0, ?)""",
        (kode, user_id, nominal, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def get_kode_unik(kode):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM kode_unik_topup WHERE kode=?", (kode,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "kode": row[0],
            "user_id": row[1],
            "nominal": row[2],
            "digunakan": row[3],
            "dibuat_pada": row[4],
            "digunakan_pada": row[5]
        }
    return None

def gunakan_kode_unik(kode):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE kode_unik_topup SET digunakan=1, digunakan_pada=? WHERE kode=?",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), kode))
    conn.commit()
    conn.close()

def get_kode_unik_user(user_id, limit=5):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM kode_unik_topup WHERE user_id=? ORDER BY dibuat_pada DESC LIMIT ?", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            "kode": row[0],
            "user_id": row[1],
            "nominal": row[2],
            "digunakan": row[3],
            "dibuat_pada": row[4],
            "digunakan_pada": row[5]
        })
    return result

# Fungsi untuk memperbarui cache produk di background
def update_produk_cache_background():
    if produk_cache["update_in_progress"]:
        return
        
    produk_cache["update_in_progress"] = True
    try:
        start_time = time.time()
        res = requests.get(cfg["BASE_URL_AKRAB"] + "cek_stock_akrab", timeout=10)
        data = res.json()
        
        if isinstance(data.get("data"), list):
            produk_cache["data"] = data["data"]
            produk_cache["last_updated"] = time.time()
            logger.info(f"Cache produk diperbarui. Jumlah produk: {len(data['data'])}. Waktu: {time.time() - start_time:.2f}s")
        else:
            logger.error("Format data stok tidak dikenali")
    except Exception as e:
        logger.error(f"Gagal memperbarui cache produk: {e}")
    finally:
        produk_cache["update_in_progress"] = False

# Conversation states
CHOOSING_PRODUK, INPUT_TUJUAN, KONFIRMASI, BC_MESSAGE, TOPUP_AMOUNT, TOPUP_UPLOAD, ADMIN_CEKUSER, ADMIN_EDIT_HARGA, ADMIN_EDIT_DESKRIPSI, INPUT_KODE_UNIK = range(10)

# UI components modern dengan emoji dan layout yang lebih baik
def btn_kembali(): 
    return [InlineKeyboardButton("🔙 Kembali", callback_data="main_menu")]

def btn_kembali_menu(): 
    return [InlineKeyboardButton("🏠 Menu Utama", callback_data="main_menu")]

def menu_user(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Beli Produk", callback_data='beli_produk'),
         InlineKeyboardButton("💳 Top Up Saldo", callback_data='topup_menu')],
        [InlineKeyboardButton("📋 Riwayat Transaksi", callback_data='riwayat'),
         InlineKeyboardButton("📦 Info Stok", callback_data='cek_stok')],
        [InlineKeyboardButton("🧾 Riwayat Top Up", callback_data="topup_riwayat"),
         InlineKeyboardButton("🔑 Kode Unik Saya", callback_data="my_kode_unik")],
        [InlineKeyboardButton("ℹ️ Bantuan", callback_data="bantuan")],
        btn_kembali_menu()
    ])

def menu_admin(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Beli Produk", callback_data='beli_produk'),
         InlineKeyboardButton("💳 Top Up Saldo", callback_data='topup_menu')],
        [InlineKeyboardButton("📋 Riwayat Saya", callback_data='riwayat'),
         InlineKeyboardButton("📦 Info Stok", callback_data='cek_stok')],
        [InlineKeyboardButton("👥 Admin Panel", callback_data='admin_panel')],
        [InlineKeyboardButton("ℹ️ Bantuan", callback_data="bantuan")],
        btn_kembali_menu()
    ])

def admin_panel_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 Data User", callback_data='admin_cekuser'),
         InlineKeyboardButton("💰 Lihat Saldo", callback_data='lihat_saldo')],
        [InlineKeyboardButton("📊 Semua Riwayat", callback_data='semua_riwayat'),
         InlineKeyboardButton("📢 Broadcast", callback_data='broadcast')],
        [InlineKeyboardButton("✅ Approve Top Up", callback_data="admin_topup_pending"),
         InlineKeyboardButton("⚙️ Manajemen Produk", callback_data="admin_produk")],
        [InlineKeyboardButton("🔑 Generate Kode Unik", callback_data="admin_generate_kode")],
        btn_kembali()
    ])

def topup_menu_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 QRIS (Otomatis)", callback_data="topup_qris")],
        [InlineKeyboardButton("🔑 Kode Unik (Manual)", callback_data="topup_kode_unik")],
        btn_kembali()
    ])

def get_menu(uid): 
    return menu_admin(uid) if uid in ADMIN_IDS else menu_user(uid)

def dashboard_msg(user):
    saldo = get_saldo(user.id)
    total_trx = get_riwayat_jml(user.id)
    msg = (
        f"✨ <b>DASHBOARD USER</b> ✨\n\n"
        f"👤 <b>{user.full_name}</b>\n"
        f"📧 @{user.username or '-'}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"💰 <b>Saldo:</b> <code>Rp {saldo:,}</code>\n"
        f"📊 <b>Total Transaksi:</b> <b>{total_trx}</b>\n"
    )
    return msg

# Command handlers
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    tambah_user(user.id, user.username or "", user.full_name)
    update.message.reply_text(
        dashboard_msg(user) + "\n📋 Pilih menu di bawah:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_menu(user.id)
    )

def main_menu_callback(update: Update, context: CallbackContext):
    user = update.effective_user
    if update.callback_query:
        update.callback_query.answer()
        update.callback_query.edit_message_text(
            dashboard_msg(user) + "\n📋 Pilih menu di bawah:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_menu(user.id)
        )
    else:
        update.message.reply_text(
            dashboard_msg(user) + "\n📋 Pilih menu di bawah:",
            parse_mode=ParseMode.HTML,
            reply_markup=get_menu(user.id)
        )
    return ConversationHandler.END

def menu_command(update: Update, context: CallbackContext):
    return main_menu_callback(update, context)

def cek_stok_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    # Gunakan data dari cache
    if produk_cache["data"]:
        data = {"data": produk_cache["data"]}
    else:
        # Jika cache kosong, ambil data langsung
        try:
            res = requests.get(cfg["BASE_URL_AKRAB"] + "cek_stock_akrab", timeout=10)
            data = res.json()
        except Exception as e:
            query.edit_message_text(f"❌ Gagal mengambil data stok: {e}", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))
            return ConversationHandler.END
    
    msg = "📦 <b>Info Stok Akrab XL/Axis</b>\n\n"
    if isinstance(data.get("data"), list):
        for produk in data["data"]:
            status = "✅" if int(produk['sisa_slot']) > 0 else "❌"
            msg += f"{status} <b>[{produk['type']}]</b> {produk['nama']}: {produk['sisa_slot']} unit\n"
    else:
        msg += "❌ Format data stok tidak dikenali."
    
    query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    return ConversationHandler.END

# Product related functions
def get_harga_produk(kode, api_produk=None):
    admin_data = get_produk_admin(kode)
    if admin_data and admin_data["harga"] and admin_data["harga"] > 0:
        return admin_data["harga"]
    
    # Jika ada data produk dari API, gunakan harganya
    if api_produk and "harga" in api_produk:
        return int(api_produk["harga"])
    
    # Jika tidak ada data, coba ambil dari cache atau API
    try:
        if produk_cache["data"]:
            for produk in produk_cache["data"]:
                if produk["type"] == kode:
                    return int(produk.get("harga", 0))
        else:
            res = requests.get(cfg["BASE_URL_AKRAB"] + "cek_stock_akrab", timeout=10)
            data = res.json()
            for produk in data.get("data", []):
                if produk["type"] == kode:
                    return int(produk.get("harga", 0))
    except Exception:
        pass
    
    return 0

def produk_inline_keyboard(is_admin=False):
    try:
        # Gunakan data dari cache jika tersedia dan masih fresh
        current_time = time.time()
        if current_time - produk_cache["last_updated"] > CACHE_DURATION:
            # Mulai update cache di background thread
            thread = threading.Thread(target=update_produk_cache_background)
            thread.daemon = True
            thread.start()
        
        data = {"data": produk_cache["data"]} if produk_cache["data"] else None
        
        # Jika cache kosong, ambil data langsung (blocking)
        if not data:
            res = requests.get(cfg["BASE_URL_AKRAB"] + "cek_stock_akrab", timeout=10)
            data = res.json()
            # Simpan ke cache
            if isinstance(data.get("data"), list):
                produk_cache["data"] = data["data"]
                produk_cache["last_updated"] = current_time
        
        keyboard = []
        
        # Dapatkan semua produk dari database admin
        admin_produk = get_all_produk_admin()
        
        if isinstance(data.get("data"), list):
            for produk in data["data"]:
                kode = produk['type']
                nama = produk['nama']
                slot = int(produk.get('sisa_slot', 0))
                harga = get_harga_produk(kode, produk)
                
                # Untuk admin, tampilkan semua produk bahkan yang stok 0
                if is_admin:
                    status = "✅" if slot > 0 else "❌"
                    label = f"{status} [{kode}] {nama} | Rp{harga:,}"
                    keyboard.append([InlineKeyboardButton(label, callback_data=f"admin_produk_detail|{kode}")])
                else:
                    # Untuk user biasa, hanya tampilkan yang stok > 0
                    if slot > 0:
                        label = f"✅ [{kode}] {nama} | Rp{harga:,}"
                        keyboard.append([InlineKeyboardButton(label, callback_data=f"produk|{kode}|{nama}")])
        
        # Tambahkan produk yang ada di database admin tapi tidak di API
        for kode, info in admin_produk.items():
            if not any(kode == p['type'] for p in data.get("data", [])):
                label = f"⚠️ [{kode}] (Tidak di API) | Rp{info['harga']:,}"
                if is_admin:
                    keyboard.append([InlineKeyboardButton(label, callback_data=f"admin_produk_detail|{kode}")])
        
        if not keyboard:
            keyboard.append([InlineKeyboardButton("❌ Tidak ada produk tersedia", callback_data="disabled_produk")])
        keyboard.append(btn_kembali())
        return InlineKeyboardMarkup(keyboard)
    except Exception as e:
        logger.error(f"Error loading products: {e}")
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Ulangi", callback_data="beli_produk")], btn_kembali()])

def beli_produk_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    # Kirim pesan loading terlebih dahulu
    query.edit_message_text(
        "🔄 Memuat daftar produk...",
        reply_markup=InlineKeyboardMarkup([btn_kembali()])
    )
    
    # Dapatkan keyboard produk (mungkin butuh waktu)
    keyboard = produk_inline_keyboard()
    
    # Update pesan dengan daftar produk
    query.edit_message_text(
        "🛒 <b>PILIH PRODUK</b>\n\nPilih produk yang ingin dibeli:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard
    )
    return CHOOSING_PRODUK

def pilih_produk_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    if data.startswith("produk|"):
        try:
            _, kode, nama = data.split("|")
            
            # Dapatkan harga produk dari cache jika tersedia
            harga = 0
            produk_api = None
            
            if produk_cache["data"]:
                for p in produk_cache["data"]:
                    if p["type"] == kode:
                        produk_api = p
                        break
            
            # Jika tidak ditemukan di cache, cari di API
            if not produk_api:
                try:
                    res = requests.get(cfg["BASE_URL_AKRAB"] + "cek_stock_akrab", timeout=10)
                    data_api = res.json()
                    for p in data_api.get("data", []):
                        if p["type"] == kode:
                            produk_api = p
                            break
                except Exception:
                    pass
            
            harga = get_harga_produk(kode, produk_api)
            
            context.user_data["produk"] = {"kode": kode, "nama": nama, "harga": harga}
            
            admin_data = get_produk_admin(kode)
            deskripsi = admin_data["deskripsi"] if admin_data and admin_data["deskripsi"] else ""
            if deskripsi:
                desc_show = f"\n📝 <b>Deskripsi:</b>\n<code>{deskripsi}</code>\n"
            else:
                desc_show = ""
                
            query.edit_message_text(
                f"✅ <b>Produk Dipilih:</b>\n\n"
                f"📦 <b>[{kode}] {nama}</b>\n"
                f"💰 <b>Harga:</b> Rp {harga:,}\n"
                f"{desc_show}\n"
                f"📱 <b>Masukkan nomor tujuan:</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([btn_kembali()])
            )
            return INPUT_TUJUAN
        except Exception as e:
            logger.error(f"Error in pilih_produk_callback: {e}")
            query.edit_message_text("❌ Terjadi kesalahan saat memilih produk.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
            return ConversationHandler.END
    elif data == "disabled_produk":
        query.answer("⚠️ Produk ini sedang habis!", show_alert=True)
        return ConversationHandler.END
    return ConversationHandler.END

def input_tujuan_step(update: Update, context: CallbackContext):
    tujuan = update.message.text.strip()
    if not tujuan.isdigit() or len(tujuan) < 8:
        update.message.reply_text("❌ Nomor tidak valid, masukkan ulang:", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return INPUT_TUJUAN
    context.user_data["tujuan"] = tujuan
    produk = context.user_data["produk"]
    admin_data = get_produk_admin(produk["kode"])
    deskripsi = admin_data["deskripsi"] if admin_data and admin_data["deskripsi"] else ""
    if deskripsi:
        desc_show = f"\n📝 <b>Deskripsi:</b>\n<code>{deskripsi}</code>\n"
    else:
        desc_show = ""
    update.message.reply_text(
        f"✅ <b>KONFIRMASI PEMESANAN</b>\n\n"
        f"📦 <b>Produk:</b> [{produk['kode']}] {produk['nama']}\n"
        f"💰 <b>Harga:</b> Rp {produk['harga']:,}\n"
        f"📱 <b>Nomor Tujuan:</b> <code>{tujuan}</code>\n"
        f"{desc_show}\n"
        f"⚠️ <b>Ketik 'YA' untuk konfirmasi atau 'BATAL' untuk membatalkan.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([btn_kembali()])
    )
    return KONFIRMASI

def konfirmasi_step(update: Update, context: CallbackContext):
    text = update.message.text.strip().upper()
    if text == "BATAL":
        update.message.reply_text("❌ Transaksi dibatalkan.", reply_markup=get_menu(update.effective_user.id))
        return ConversationHandler.END
    if text != "YA":
        update.message.reply_text("❌ Ketik 'YA' untuk konfirmasi atau 'BATAL' untuk batal.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return KONFIRMASI
        
    produk = context.user_data["produk"]
    tujuan = context.user_data["tujuan"]
    user = update.effective_user
    
    harga = produk.get("harga", 0)
    if harga <= 0:
        harga = get_harga_produk(produk["kode"])
    
    saldo = get_saldo(user.id)
    if saldo < harga:
        update.message.reply_text("❌ Saldo Anda tidak cukup.", reply_markup=get_menu(user.id))
        return ConversationHandler.END
        
    # Kurangi saldo di awal
    kurang_saldo(user.id, harga)
    
    reffid = str(uuid.uuid4())
    url = f"{BASE_URL}trx?produk={produk['kode']}&tujuan={tujuan}&reff_id={reffid}&api_key={API_KEY}"
    
    try:
        data = requests.get(url, timeout=15).json()
    except Exception as e:
        # Jika request gagal, kembalikan saldo
        tambah_saldo(user.id, harga)
        update.message.reply_text(f"❌ Gagal request ke provider. Saldo Anda telah dikembalikan.\n\nDetail: {e}", reply_markup=get_menu(user.id))
        return ConversationHandler.END
        
    status_text = data.get('status', 'PENDING')
    keterangan = data.get('message', 'Transaksi sedang diproses.')
    
    # Catat transaksi sebagai PENDING
    log_riwayat(reffid, user.id, produk["kode"], tujuan, harga, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), status_text, keterangan)
    
    update.message.reply_text(
        f"⏳ <b>TRANSAKSI SEDANG DIPROSES</b>\n\n"
        f"📦 <b>Produk:</b> [{produk['kode']}] {produk['nama']}\n"
        f"📱 <b>Tujuan:</b> {tujuan}\n"
        f"🔖 <b>RefID:</b> <code>{reffid}</code>\n"
        f"📊 <b>Status:</b> {status_text.upper()}\n"
        f"💬 Keterangan: {keterangan}\n\n"
        f"Mohon tunggu beberapa saat untuk pembaruan status.",
        parse_mode=ParseMode.HTML,
        reply_markup=get_menu(user.id)
    )
    return ConversationHandler.END

# ================= ADMIN PRODUK MANAGEMENT =================
def admin_produk_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        "⚙️ <b>MANAJEMEN PRODUK</b>\n\nEdit harga/deskripsi produk:",
        parse_mode=ParseMode.HTML,
        reply_markup=produk_inline_keyboard(is_admin=True)
    )
    return ADMIN_CEKUSER

def admin_produk_detail(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        kode = query.data.split("|")[1]
        
        # Coba dapatkan info produk dari cache
        produk_api = None
        if produk_cache["data"]:
            for p in produk_cache["data"]:
                if p["type"] == kode:
                    produk_api = p
                    break
        
        # Jika tidak ditemukan di cache, coba dari API
        if not produk_api:
            try:
                res = requests.get(cfg["BASE_URL_AKRAB"] + "cek_stock_akrab", timeout=10)
                data = res.json()
                for p in data.get("data", []):
                    if p["type"] == kode:
                        produk_api = p
                        break
            except Exception:
                pass
                
        # Dapatkan info dari database admin
        admin_data = get_produk_admin(kode)
        harga_bot = admin_data["harga"] if admin_data and admin_data["harga"] else (int(produk_api["harga"]) if produk_api and "harga" in produk_api else 0)
        deskripsi_bot = admin_data["deskripsi"] if admin_data and admin_data["deskripsi"] else ""
        
        msg = f"📦 <b>DETAIL PRODUK</b>\n\n<b>Kode:</b> {kode}\n"
        
        if produk_api:
            msg += (
                f"<b>Nama:</b> {produk_api['nama']}\n"
                f"<b>Stok:</b> {produk_api.get('sisa_slot', 0)}\n"
                f"<b>Harga API:</b> Rp{int(produk_api.get('harga', 0)):,}\n"
            )
        else:
            msg += "<b>Nama:</b> Produk tidak ditemukan di API\n"
        
        msg += (
            f"<b>Harga Bot:</b> Rp{harga_bot:,}\n"
            f"<b>Deskripsi:</b>\n<code>{deskripsi_bot if deskripsi_bot else 'Tidak ada deskripsi'}</code>"
        )
        
        keyboard = [
            [InlineKeyboardButton("✏️ Edit Harga", callback_data=f"admin_edit_harga|{kode}"),
             InlineKeyboardButton("📝 Edit Deskripsi", callback_data=f"admin_edit_deskripsi|{kode}")],
            [InlineKeyboardButton("🔙 Kembali ke Daftar Produk", callback_data="admin_produk")],
            btn_kembali()
        ]
        query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error in admin_produk_detail: {e}")
        query.edit_message_text("❌ Terjadi kesalahan saat memuat detail produk.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    return ADMIN_CEKUSER

def admin_edit_harga(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        kode = query.data.split("|")[1]
        context.user_data["admin_edit_kode"] = kode
        
        # Dapatkan harga saat ini
        admin_data = get_produk_admin(kode)
        harga_sekarang = admin_data["harga"] if admin_data and admin_data["harga"] else 0
        
        query.edit_message_text(
            f"💰 <b>EDIT HARGA PRODUK</b>\n\n"
            f"Kode: <b>{kode}</b>\n"
            f"Harga saat ini: <b>Rp {harga_sekarang:,}</b>\n\n"
            f"Masukkan harga baru (angka saja):",
            parse_mode=ParseMode.HTML, 
            reply_markup=InlineKeyboardMarkup([btn_kembali()])
        )
        return ADMIN_EDIT_HARGA
    except Exception as e:
        logger.error(f"Error in admin_edit_harga: {e}")
        query.edit_message_text("❌ Terjadi kesalahan.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return ConversationHandler.END

def admin_edit_harga_step(update: Update, context: CallbackContext):
    try:
        kode = context.user_data.get("admin_edit_kode")
        text = update.message.text.replace(".", "").replace(",", "")
        if not text.isdigit() or int(text) <= 0:
            update.message.reply_text("❌ Input harga salah. Masukkan angka lebih dari 0.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
            return ADMIN_EDIT_HARGA
            
        harga = int(text)
        set_produk_admin_harga(kode, harga)
        
        # Kembali ke detail produk
        admin_data = get_produk_admin(kode)
        deskripsi_bot = admin_data["deskripsi"] if admin_data and admin_data["deskripsi"] else ""
        
        msg = (
            f"✅ <b>HARGA BERHASIL DIUPDATE</b>\n\n"
            f"<b>Kode:</b> {kode}\n"
            f"<b>Harga Baru:</b> Rp{harga:,}\n"
            f"<b>Deskripsi:</b>\n<code>{deskripsi_bot if deskripsi_bot else 'Tidak ada deskripsi'}</code>"
        )
        
        keyboard = [
            [InlineKeyboardButton("✏️ Edit Harga", callback_data=f"admin_edit_harga|{kode}"),
             InlineKeyboardButton("📝 Edit Deskripsi", callback_data=f"admin_edit_deskripsi|{kode}")],
            [InlineKeyboardButton("🔙 Kembali ke Daftar Produk", callback_data="admin_produk")],
            btn_kembali()
        ]
        
        update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error in admin_edit_harga_step: {e}")
        update.message.reply_text("❌ Terjadi kesalahan saat mengupdate harga.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    return ConversationHandler.END

def admin_edit_deskripsi(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        kode = query.data.split("|")[1]
        context.user_data["admin_edit_kode"] = kode
        
        # Dapatkan deskripsi saat ini
        admin_data = get_produk_admin(kode)
        deskripsi_sekarang = admin_data["deskripsi"] if admin_data and admin_data["deskripsi"] else ""
        
        query.edit_message_text(
            f"📝 <b>EDIT DESKRIPSI PRODUK</b>\n\n"
            f"Kode: <b>{kode}</b>\n"
            f"Deskripsi saat ini:\n<code>{deskripsi_sekarang}</code>\n\n"
            f"Ketik deskripsi baru:",
            parse_mode=ParseMode.HTML, 
            reply_markup=InlineKeyboardMarkup([btn_kembali()])
        )
        return ADMIN_EDIT_DESKRIPSI
    except Exception as e:
        logger.error(f"Error in admin_edit_deskripsi: {e}")
        query.edit_message_text("❌ Terjadi kesalahan.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return ConversationHandler.END

def admin_edit_deskripsi_step(update: Update, context: CallbackContext):
    try:
        kode = context.user_data.get("admin_edit_kode")
        deskripsi = update.message.text.strip()
        
        set_produk_admin_deskripsi(kode, deskripsi)
        
        # Kembali ke detail produk
        admin_data = get_produk_admin(kode)
        harga_bot = admin_data["harga"] if admin_data and admin_data["harga"] else 0
        
        msg = (
            f"✅ <b>DESKRIPSI BERHASIL DIUPDATE</b>\n\n"
            f"<b>Kode:</b> {kode}\n"
            f"<b>Harga:</b> Rp{harga_bot:,}\n"
            f"<b>Deskripsi Baru:</b>\n<code>{deskripsi}</code>"
        )
        
        keyboard = [
            [InlineKeyboardButton("✏️ Edit Harga", callback_data=f"admin_edit_harga|{kode}"),
             InlineKeyboardButton("📝 Edit Deskripsi", callback_data=f"admin_edit_deskripsi|{kode}")],
            [InlineKeyboardButton("🔙 Kembali ke Daftar Produk", callback_data="admin_produk")],
            btn_kembali()
        ]
        
        update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Error in admin_edit_deskripsi_step: {e}")
        update.message.reply_text("❌ Terjadi kesalahan saat mengupdate deskripsi.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    return ConversationHandler.END

def admin_cekuser_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        users = get_all_users()
        keyboard = []
        for u in users:
            label = f"{u[2]} (@{u[1]}) [{u[0]}]"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"admin_cekuser_detail|{u[0]}")])
        keyboard.append(btn_kembali())
        query.edit_message_text(
            "👥 <b>DAFTAR USER TERDAFTAR</b>\n\nPilih user untuk melihat detail:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in admin_cekuser_menu: {e}")
        query.edit_message_text("❌ Terjadi kesalahan saat memuat daftar user.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    return ConversationHandler.END

def admin_cekuser_detail_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        # Pastikan data memiliki format yang benar
        if "|" in query.data:
            user_id = int(query.data.split("|")[1])
            user = get_user(user_id)
            if user:
                saldo = get_saldo(user_id)
                jml_transaksi = get_riwayat_jml(user_id)
                msg = (
                    f"👤 <b>DETAIL USER</b>\n\n"
                    f"<b>Nama:</b> {user[2]}\n"
                    f"<b>Username:</b> @{user[1]}\n"
                    f"<b>ID:</b> <code>{user[0]}</code>\n"
                    f"<b>Saldo:</b> Rp {saldo:,}\n"
                    f"<b>Jumlah Transaksi:</b> {jml_transaksi}"
                )
                query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))
            else:
                query.edit_message_text("❌ User tidak ditemukan.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        else:
            query.edit_message_text("❌ Format data tidak valid.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing user_id: {e}, data: {query.data}")
        query.edit_message_text("❌ Terjadi kesalahan saat memproses data.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    except Exception as e:
        logger.error(f"Unexpected error in admin_cekuser_detail_callback: {e}")
        query.edit_message_text("❌ Terjadi kesalahan yang tidak terduga.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    return ConversationHandler.END

# Top up functions
def topup_menu(update, context):
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        "💳 <b>TOP UP SALDO</b>\n\nPilih metode top up:",
        parse_mode=ParseMode.HTML,
        reply_markup=topup_menu_buttons()
    )
    return TOPUP_AMOUNT

def topup_qris_amount(update, context):
    query = update.callback_query
    query.edit_message_text(
        "💰 <b>TOP UP VIA QRIS</b>\n\nMasukkan nominal top up saldo (minimal 10.000, maksimal 5.000.000, kelipatan 1000):",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([btn_kembali()])
    )
    context.user_data['topup_method'] = 'qris'
    return TOPUP_AMOUNT

def topup_kode_unik_menu(update, context):
    query = update.callback_query
    query.edit_message_text(
        "🔑 <b>TOP UP VIA KODE UNIK</b>\n\nMasukkan kode unik yang diberikan admin:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([btn_kembali()])
    )
    context.user_data['topup_method'] = 'kode_unik'
    return INPUT_KODE_UNIK

def input_kode_unik_step(update, context):
    kode = update.message.text.strip()
    user = update.effective_user
    
    # Cek kode unik
    kode_data = get_kode_unik(kode)
    if not kode_data:
        update.message.reply_text("❌ Kode unik tidak valid atau tidak ditemukan.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return INPUT_KODE_UNIK
        
    if kode_data["digunakan"]:
        update.message.reply_text("❌ Kode unik sudah digunakan.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return INPUT_KODE_UNIK
        
    # Gunakan kode unik
    tambah_saldo(user.id, kode_data["nominal"])
    gunakan_kode_unik(kode)
    
    update.message.reply_text(
        f"✅ <b>TOP UP BERHASIL</b>\n\n"
        f"Kode unik: <b>{kode}</b>\n"
        f"Nominal: <b>Rp {kode_data['nominal']:,}</b>\n"
        f"Saldo sekarang: <b>Rp {get_saldo(user.id):,}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_menu(user.id)
    )
    return ConversationHandler.END

def generate_qris(amount, qris_statis):
    url = "https://qrisku.my.id/api"
    payload = {"amount": str(amount), "qris_statis": qris_statis}
    try:
        res = requests.post(url, json=payload, timeout=20)
        data = res.json()
        if data['status'] == 'success' and 'qris_base64' in data:
            return True, data['qris_base64']
        else:
            return False, data.get('message', 'Gagal generate QRIS')
    except Exception as e:
        return False, f"Error koneksi API QRIS: {e}"

def topup_amount_step(update, context):
    try:
        nominal = int(update.message.text.replace(".", "").replace(",", ""))
        if nominal < 10000 or nominal > 5000000 or nominal % 1000 != 0:
            raise Exception
    except Exception:
        update.message.reply_text("❌ Nominal kelipatan 1.000, min 10.000, max 5.000.000. Masukkan kembali:", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return TOPUP_AMOUNT
        
    user = update.effective_user
    
    # Tambahkan nominal unik
    unique_code = random.randint(100, 999)
    final_nominal = nominal + unique_code
    
    sukses, hasil = generate_qris(final_nominal, QRIS_STATIS)
    if sukses:
        try:
            img_bytes = base64.b64decode(hasil)
            topup_id = str(uuid.uuid4())
            insert_topup_pending(topup_id, user.id, user.username or "", user.full_name, final_nominal, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "pending")
            
            # Notify admins
            for adm in ADMIN_IDS:
                try:
                    context.bot.send_message(
                        chat_id=adm,
                        text=f"🔔 Permintaan top up QRIS baru!\nUser: <b>{user.full_name}</b> (@{user.username or '-'})\nID: <code>{user.id}</code>\nNominal: <b>Rp {final_nominal:,}</b>\n\nSilakan cek menu Approve Top Up QRIS.",
                        parse_mode=ParseMode.HTML)
                except Exception as e:
                    logger.error(f"Notif admin gagal: {e}")
                    
            update.message.reply_photo(photo=img_bytes, caption=(
                f"💰 <b>QRIS UNTUK TOP UP</b>\n\n"
                f"Nominal: <b>Rp {final_nominal:,}</b>\n"
                f"Kode unik: <b>{unique_code}</b>\n\n"
                "Scan QRIS di atas menggunakan aplikasi e-wallet atau mobile banking Anda.\n\n"
                "Setelah transfer, klik tombol di bawah untuk upload bukti transfer."
            ), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Upload Bukti Transfer", callback_data=f"topup_upload|{topup_id}")],
                btn_kembali()
            ]))
        except Exception as e:
            logger.error(f"Error QRIS: {e}")
            update.message.reply_text("❌ Gagal decode gambar QRIS.", reply_markup=get_menu(user.id))
    else:
        update.message.reply_text(f"❌ Gagal membuat QRIS: {hasil}", reply_markup=get_menu(user.id))
        
    return ConversationHandler.END

def topup_upload_router(update, context):
    query = update.callback_query
    try:
        _, topup_id = query.data.split("|")
        context.user_data['topup_upload_id'] = topup_id
        query.edit_message_text(
            "📤 <b>UPLOAD BUKTI TRANSFER</b>\n\nUpload foto bukti transfer QRIS (balas pesan ini dengan foto):",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([btn_kembali()])
        )
        return TOPUP_UPLOAD
    except Exception as e:
        logger.error(f"Error in topup_upload_router: {e}")
        query.edit_message_text("❌ Terjadi kesalahan.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return ConversationHandler.END

def topup_upload_step(update, context):
    user = update.effective_user
    topup_id = context.user_data.get('topup_upload_id')
    if not topup_id:
        update.message.reply_text("❌ ID top up tidak ditemukan. Gunakan tombol pada menu top up.", reply_markup=get_menu(user.id))
        return ConversationHandler.END
        
    if not update.message.photo:
        update.message.reply_text("❌ Hanya menerima foto sebagai bukti transfer. Silahkan upload ulang!", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return TOPUP_UPLOAD
        
    file_id = update.message.photo[-1].file_id
    caption = update.message.caption or ""
    update_topup_bukti(topup_id, file_id, caption)
    
    # Notify admins
    for adm in ADMIN_IDS:
        try:
            context.bot.send_message(
                chat_id=adm,
                text=f"🔔 Bukti transfer QRIS masuk dari user <b>{user.full_name}</b> (@{user.username or '-'})",
                parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Notif admin gagal: {e}")
            
    context.user_data['topup_upload_id'] = None
    update.message.reply_text("✅ Bukti transfer berhasil dikirim. Silakan tunggu admin verifikasi.", reply_markup=get_menu(user.id))
    return ConversationHandler.END

def topup_riwayat_menu(update: Update, context: CallbackContext):
    user = update.effective_user
    items = get_topup_pending_by_user(user.id, 10)
    msg = "📋 <b>RIWAYAT TOP UP ANDA (10 terbaru)</b>\n\n"
    if not items:
        msg += "Belum ada permintaan top up."
    else:
        for r in items:
            emoji = "⏳" if r[6]=="pending" else ("✅" if r[6]=="approved" else "❌")
            msg += (
                f"{emoji} <b>{r[5]}</b>\n"
                f"ID: <code>{r[0]}</code>\n"
                f"Nominal: Rp {r[4]:,}\n"
                f"Status: <b>{r[6].capitalize()}</b>\n\n"
            )
            
    if update.callback_query:
        update.callback_query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    else:
        update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        
    return ConversationHandler.END

def my_kode_unik_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    user = query.from_user
    items = get_kode_unik_user(user.id, 10)
    msg = "🔑 <b>KODE UNIK SAYA (10 terbaru)</b>\n\n"
    if not items:
        msg += "Belum ada kode unik yang dibuat."
    else:
        for kode in items:
            status = "✅ Digunakan" if kode["digunakan"] else "⏳ Belum digunakan"
            msg += (
                f"Kode: <code>{kode['kode']}</code>\n"
                f"Nominal: Rp {kode['nominal']:,}\n"
                f"Status: {status}\n"
                f"Dibuat: {kode['dibuat_pada']}\n\n"
            )
            
    query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    return ConversationHandler.END

def admin_topup_pending_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    items = get_topup_pending_all(10)
    keyboard = []
    for r in items:
        label = f"{r[3]} | Rp{r[4]:,} | {r[5]}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"admin_topup_detail|{r[0]}")])
    if not keyboard:
        keyboard.append([InlineKeyboardButton("✅ Tidak ada top up pending", callback_data="main_menu")])
    keyboard.append(btn_kembali())
    query.edit_message_text(
        "📋 <b>PERMINTAAN TOP UP PENDING (10 terbaru)</b>\n\nPilih untuk melihat detail:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

def admin_topup_detail(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        topup_id = query.data.split("|")[1]
        r = get_topup_by_id(topup_id)
        if not r:
            query.answer("❌ Data tidak ditemukan.", show_alert=True)
            return ConversationHandler.END
            
        caption = (
            f"📋 <b>DETAIL TOP UP</b>\n\n"
            f"👤 <b>User:</b> {r[3]} (@{r[2]})\n"
            f"🆔 <b>User ID:</b> <code>{r[1]}</code>\n"
            f"💰 <b>Nominal:</b> Rp {r[4]:,}\n"
            f"⏰ <b>Waktu:</b> {r[5]}\n"
            f"📊 <b>Status:</b> {r[6].capitalize()}\n"
            f"🔖 <b>ID Top Up:</b> <code>{r[0]}</code>\n"
        )
        actions = [
            [InlineKeyboardButton("✅ Approve", callback_data=f"admin_topup_action|approve|{topup_id}"),
             InlineKeyboardButton("❌ Reject", callback_data=f"admin_topup_action|reject|{topup_id}")]
        ]
        actions.append(btn_kembali())
        
        if r[7]:
            query.edit_message_media(
                InputMediaPhoto(r[7], caption=caption, parse_mode=ParseMode.HTML),
                reply_markup=InlineKeyboardMarkup(actions)
            )
        else:
            query.edit_message_text(caption + "\n\n❌ Belum ada bukti transfer", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(actions))
    except Exception as e:
        logger.error(f"Error in admin_topup_detail: {e}")
        query.edit_message_text("❌ Terjadi kesalahan saat memuat detail top up.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    return ConversationHandler.END

def admin_topup_action(update: Update, context: CallbackContext):
    query = update.callback_query
    try:
        _, action, topup_id = query.data.split("|")
        r = get_topup_by_id(topup_id)
        if not r:
            query.answer("❌ Data tidak ditemukan.", show_alert=True)
            return ConversationHandler.END
            
        if action == "approve":
            tambah_saldo(r[1], r[4])
            update_topup_status(topup_id, "approved")
            try:
                context.bot.send_message(r[1], 
                    f"✅ <b>TOP UP DISETUJUI</b>\n\n"
                    f"Top up sebesar Rp {r[4]:,} telah disetujui!\n"
                    f"Saldo Anda sekarang: Rp {get_saldo(r[1]):,}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_menu(r[1]))
            except Exception as e:
                logger.error(f"Notif approve gagal: {e}")
            query.answer("✅ Top up berhasil disetujui.", show_alert=True)
        elif action == "reject":
            update_topup_status(topup_id, "rejected")
            try:
                context.bot.send_message(r[1], 
                    f"❌ <b>TOP UP DITOLAK</b>\n\n"
                    f"Top up sebesar Rp {r[4]:,} ditolak oleh admin.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_menu(r[1]))
            except Exception as e:
                logger.error(f"Notif reject gagal: {e}")
            query.answer("❌ Top up ditolak.", show_alert=True)
            
        return admin_topup_pending_menu(update, context)
    except Exception as e:
        logger.error(f"Error in admin_topup_action: {e}")
        query.edit_message_text("❌ Terjadi kesalahan saat memproses aksi.", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return ConversationHandler.END

def admin_generate_kode(update: Update, context: CallbackContext):
    query = update.callback_query
    query.edit_message_text(
        "🔑 <b>GENERATE KODE UNIK</b>\n\nMasukkan nominal untuk kode unik (min 10.000):",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([btn_kembali()])
    )
    return INPUT_KODE_UNIK

def admin_generate_kode_step(update: Update, context: CallbackContext):
    try:
        nominal = int(update.message.text.replace(".", "").replace(",", ""))
        if nominal < 10000:
            update.message.reply_text("❌ Minimal nominal 10.000", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
            return INPUT_KODE_UNIK
            
        kode = generate_kode_unik()
        simpan_kode_unik(kode, update.effective_user.id, nominal)
        
        update.message.reply_text(
            f"✅ <b>KODE UNIK BERHASIL DIBUAT</b>\n\n"
            f"Kode: <code>{kode}</code>\n"
            f"Nominal: <b>Rp {nominal:,}</b>\n\n"
            f"Berikan kode ini kepada user untuk top up saldo.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_menu(update.effective_user.id)
        )
    except ValueError:
        update.message.reply_text("❌ Masukkan angka yang valid", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return INPUT_KODE_UNIK
    except Exception as e:
        logger.error(f"Error generating kode: {e}")
        update.message.reply_text("❌ Terjadi kesalahan", reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    
    return ConversationHandler.END

# History functions
def riwayat_user(query, context):
    user = query.from_user
    items = get_riwayat_user(user.id)
    msg = "📋 <b>RIWAYAT TRANSAKSI ANDA (10 terbaru)</b>\n\n"
    if not items:
        msg += "Belum ada transaksi."
    else:
        for r in items:
            status = r[6].upper()
            emoji = "✅" if "SUKSES" in status else ("❌" if "GAGAL" in status or "BATAL" in status else "⏳")
            msg += (
                f"{emoji} <b>{r[5]}</b>\n"
                f"ID: <code>{r[0]}</code>\n"
                f"Produk: [{r[2]}] ke {r[3]}\n"
                f"Harga: Rp {r[4]:,}\n"
                f"Status: <b>{status}</b>\n"
                f"Keterangan: {r[7]}\n\n"
            )
    query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))

def semua_riwayat_admin(query, context):
    items = get_all_riwayat()
    msg = "📋 <b>SEMUA RIWAYAT TRANSAKSI (10 terbaru)</b>\n\n"
    if not items:
        msg += "Belum ada transaksi."
    else:
        for r in items:
            status = r[6].upper()
            emoji = "✅" if "SUKSES" in status else ("❌" if "GAGAL" in status or "BATAL" in status else "⏳")
            user = get_user(r[1])
            username = f"@{user[1]}" if user and user[1] else "Unknown"
            msg += (
                f"{emoji} <b>{r[5]}</b>\n"
                f"User: {username} ({r[1]})\n"
                f"Produk: [{r[2]}] ke {r[3]}\n"
                f"Harga: Rp {r[4]:,}\n"
                f"Status: <b>{status}</b>\n"
                f"Keterangan: {r[7]}\n\n"
            )
    query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))

# Broadcast function
def broadcast_step(update: Update, context: CallbackContext):
    text = update.message.text
    users = get_all_users()
    count = 0
    fail = 0
    for u in users:
        try:
            context.bot.send_message(
                chat_id=int(u[0]),
                text=f"📢 <b>BROADCAST</b>\n\n{text}",
                parse_mode=ParseMode.HTML
            )
            count += 1
        except Exception:
            fail += 1
    update.message.reply_text(
        f"✅ <b>BROADCAST SELESAI</b>\n\nBerhasil: {count}\nGagal: {fail}",
        parse_mode=ParseMode.HTML,
        reply_markup=get_menu(update.effective_user.id)
    )
    return ConversationHandler.END

def bantuan_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    msg = (
        "❓ <b>BANTUAN</b>\n\n"
        "📋 <b>Cara menggunakan bot:</b>\n"
        "1. Pilih <b>Beli Produk</b> untuk membeli produk\n"
        "2. Pilih <b>Top Up Saldo</b> untuk menambah saldo\n"
        "3. Gunakan menu <b>Riwayat</b> untuk melihat transaksi\n\n"
        "💳 <b>Metode Top Up:</b>\n"
        "- <b>QRIS</b>: Scan QR code untuk transfer\n"
        "- <b>Kode Unik</b>: Masukkan kode dari admin\n\n"
        "🛒 <b>Beli Produk:</b>\n"
        "1. Pilih produk yang tersedia\n"
        "2. Masukkan nomor tujuan\n"
        "3. Konfirmasi pembelian\n\n"
        "📞 <b>Bantuan lebih lanjut:</b>\n"
        "Hubungi admin untuk pertanyaan lainnya"
    )
    query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))
    return ConversationHandler.END

def admin_panel(update: Update, context: CallbackContext):
    query = update.callback_query
    query.edit_message_text(
        "⚙️ <b>ADMIN PANEL</b>\n\nPilih menu admin:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_panel_menu()
    )
    return ConversationHandler.END

# General handlers
def handle_text(update: Update, context: CallbackContext):
    update.message.reply_text("ℹ️ Gunakan menu untuk navigasi.", reply_markup=get_menu(update.effective_user.id))

def callback_router(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    if data == "main_menu":
        return main_menu_callback(update, context)
    elif data == "beli_produk":
        return beli_produk_menu(update, context)
    elif data.startswith("produk|") or data == "disabled_produk":
        return pilih_produk_callback(update, context)
    elif data == "cek_stok":
        return cek_stok_menu(update, context)
    elif data == "riwayat":
        riwayat_user(query, context)
        return ConversationHandler.END
    elif data == "semua_riwayat":
        semua_riwayat_admin(query, context)
        return ConversationHandler.END
    elif data == "admin_cekuser":
        return admin_cekuser_menu(update, context)
    elif data.startswith("admin_cekuser_detail|"):
        return admin_cekuser_detail_callback(update, context)
    elif data == "topup_menu":
        return topup_menu(update, context)
    elif data == "topup_qris":
        return topup_qris_amount(update, context)
    elif data == "topup_kode_unik":
        return topup_kode_unik_menu(update, context)
    elif data.startswith("topup_upload|"):
        return topup_upload_router(update, context)
    elif data == "topup_riwayat":
        topup_riwayat_menu(update, context)
        return ConversationHandler.END
    elif data == "my_kode_unik":
        my_kode_unik_menu(update, context)
        return ConversationHandler.END
    elif data == "admin_topup_pending":
        return admin_topup_pending_menu(update, context)
    elif data.startswith("admin_topup_detail|"):
        return admin_topup_detail(update, context)
    elif data.startswith("admin_topup_action|"):
        return admin_topup_action(update, context)
    elif data == "broadcast":
        query.edit_message_text("📢 Ketik pesan yang ingin di-broadcast ke semua user:", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return BC_MESSAGE
    elif data == "lihat_saldo":
        saldo = get_saldo(query.from_user.id)
        query.edit_message_text(f"💰 <b>SALDO ANDA</b>\n\nSaldo: <b>Rp {saldo:,}</b>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([btn_kembali()]))
        return ConversationHandler.END
    elif data == "admin_produk":
        return admin_produk_menu(update, context)
    elif data.startswith("admin_produk_detail|"):
        return admin_produk_detail(update, context)
    elif data.startswith("admin_edit_harga|"):
        return admin_edit_harga(update, context)
    elif data.startswith("admin_edit_deskripsi|"):
        return admin_edit_deskripsi(update, context)
    elif data == "admin_generate_kode":
        return admin_generate_kode(update, context)
    elif data == "bantuan":
        return bantuan_menu(update, context)
    elif data == "admin_panel":
        return admin_panel(update, context)
        
    return ConversationHandler.END

def run_flask_app():
    app.run(host='0.0.0.0', port=WEBHOOK_PORT)

app = Flask(__name__)

# REGEX untuk parse pesan webhook dari API Khfy-store
RX = re.compile(
    r'RC=(?P<reffid>[a-f0-9-]+)\s+TrxID=(?P<trxid>\d+)\s+'
    r'(?P<produk>[A-Z0-9]+)\.(?P<tujuan>\d+)\s+'
    r'(?P<status_text>[A-Za-z]+)\s*'
    r'(?P<keterangan>.+?)'
    r'(?:\s+Saldo[\s\S]*?)?'
    r'(?:\bresult=(?P<status_code>\d+))?\s*>?$',
    re.I
)

@app.route('/webhook', methods=['GET', 'POST'])
def webhook_handler():
    try:
        # Menambahkan logging untuk payload lengkap
        logger.info(f"[WEBHOOK RECEIVE] Headers: {request.headers}")
        logger.info(f"[WEBHOOK RECEIVE] Form Data: {request.form}")
        logger.info(f"[WEBHOOK RECEIVE] Arguments: {request.args}")

        message = request.args.get('message') or request.form.get('message')
        if not message:
            logger.warning("[WEBHOOK] Pesan kosong diterima.")
            return jsonify({'ok': False, 'error': 'message kosong'}), 400

        match = RX.match(message)
        if not match:
            logger.warning(f"[WEBHOOK] Format tidak dikenali -> {message}")
            return jsonify({'ok': False, 'error': 'format tidak dikenali'}), 200

        groups = match.groupdict()
        reffid = groups.get('reffid')
        status_text = groups.get('status_text')
        keterangan = groups.get('keterangan', '').strip()

        logger.info(f"== Webhook masuk untuk RefID: {reffid} dengan status: {status_text} ==")
        
        riwayat = get_riwayat_by_refid(reffid)
        if not riwayat:
            logger.warning(f"RefID {reffid} tidak ditemukan di database.")
            return jsonify({'ok': False, 'error': 'transaksi tidak ditemukan'}), 200
        
        user_id = riwayat[1]
        produk_kode = riwayat[2]
        harga = riwayat[4]
        
        # Periksa apakah status sudah di-update sebelumnya untuk menghindari duplikasi
        current_status = riwayat[6].lower()
        if "sukses" in current_status or "gagal" in current_status or "batal" in current_status:
            logger.info(f"RefID {reffid} sudah memiliki status final. Tidak perlu diupdate.")
            return jsonify({'ok': True, 'message': 'Status sudah final'}), 200
            
        # Perbarui status di database
        update_riwayat_status(reffid, status_text.upper(), keterangan)

        if "sukses" in status_text.lower():
            # Potong saldo, karena ini adalah konfirmasi SUKSES pertama
            kurang_saldo(user_id, harga)
            
            # Kirim notifikasi ke user
            try:
                updater.bot.send_message(user_id, 
                    f"✅ <b>TRANSAKSI SUKSES</b>\n\n"
                    f"Produk: [{produk_kode}] dengan harga Rp {harga:,} telah berhasil dikirim.\n"
                    f"Keterangan: {keterangan}\n\n"
                    f"Saldo Anda sekarang: Rp {get_saldo(user_id):,}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_menu(user_id))
            except Exception as e:
                logger.error(f"Gagal kirim notif sukses ke user {user_id}: {e}")
                
        elif "gagal" in status_text.lower() or "batal" in status_text.lower():
            # Kembalikan saldo yang sudah terlanjur dipotong
            tambah_saldo(user_id, harga)
            
            # Kirim notifikasi ke user
            try:
                updater.bot.send_message(user_id, 
                    f"❌ <b>TRANSAKSI GAGAL</b>\n\n"
                    f"Transaksi untuk produk [{produk_kode}] dengan harga Rp {harga:,} GAGAL.\n"
                    f"Keterangan: {keterangan}\n\n"
                    f"Saldo Anda telah dikembalikan. Saldo sekarang: Rp {get_saldo(user_id):,}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_menu(user_id))
            except Exception as e:
                logger.error(f"Gagal kirim notif gagal ke user {user_id}: {e}")
                
        else:
            logger.info(f"Status webhook tidak dikenal: {status_text}")
        
        return jsonify({'ok': True, 'message': 'Webhook diterima'}), 200

    except Exception as e:
        logger.error(f"[WEBHOOK][ERROR] {e}", exc_info=True)
        return jsonify({'ok': False, 'error': 'internal_error'}), 500

def main():
    init_db()
    
    logger.info("Memuat cache produk awal...")
    update_produk_cache_background()
    
    global updater
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Jalankan Flask app di thread terpisah
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('menu', menu_command))
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(callback_router)
        ],
        states={
            CHOOSING_PRODUK: [CallbackQueryHandler(pilih_produk_callback)],
            INPUT_TUJUAN: [MessageHandler(Filters.text & ~Filters.command, input_tujuan_step)],
            KONFIRMASI: [MessageHandler(Filters.text & ~Filters.command, konfirmasi_step)],
            TOPUP_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, topup_amount_step)],
            TOPUP_UPLOAD: [MessageHandler(Filters.photo, topup_upload_step)],
            BC_MESSAGE: [MessageHandler(Filters.text & ~Filters.command, broadcast_step)],
            ADMIN_CEKUSER: [
                CallbackQueryHandler(admin_produk_detail, pattern="^admin_produk_detail\\|"),
                CallbackQueryHandler(admin_edit_harga, pattern="^admin_edit_harga\\|"),
                CallbackQueryHandler(admin_edit_deskripsi, pattern="^admin_edit_deskripsi\\|")
            ],
            ADMIN_EDIT_HARGA: [MessageHandler(Filters.text & ~Filters.command, admin_edit_harga_step)],
            ADMIN_EDIT_DESKRIPSI: [MessageHandler(Filters.text & ~Filters.command, admin_edit_deskripsi_step)],
            INPUT_KODE_UNIK: [
                MessageHandler(Filters.text & ~Filters.command, input_kode_unik_step),
                MessageHandler(Filters.text & ~Filters.command, admin_generate_kode_step)
            ],
        },
        fallbacks=[
            CommandHandler('start', start),
            CommandHandler('menu', menu_command),
            CallbackQueryHandler(main_menu_callback, pattern="^main_menu$")
        ],
        allow_reentry=True,
    )
    
    dp.add_handler(conv_handler)
    dp.add_handler(CallbackQueryHandler(callback_router))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
    
    updater.start_polling()
    logger.info("Bot started polling...")
    updater.idle()

if __name__ == "__main__":
    main()
