# Bot Mila (Akrab Step Inline)

Bot Telegram untuk transaksi digital dengan fitur beli produk, top up saldo (QRIS & kode unik), riwayat transaksi, admin panel, dsb.

---

## Clone Repository

```bash
git clone https://github.com/amifistore/Mila.git
cd Mila
```

---

## Instalasi Cepat

1. **Duplikat** file `config.json.example` jadi `config.json`, lalu isi semua field dengan data Anda.
2. (Opsional) Buat dan aktifkan virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
3. **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    Atau cukup jalankan:
    ```bash
    bash install.sh
    ```
4. **Jalankan bot**:
    ```bash
    python bot_akrab_step_inline.py
    ```

---

## Konfigurasi

- **config.json** (WAJIB diisi):
    - `TOKEN`: Token bot Telegram Anda.
    - `ADMIN_IDS`: List ID admin Telegram (angka).
    - `BASE_URL`, `API_KEY`, `BASE_URL_AKRAB`: URL & API Key provider produk Anda.
    - `QRIS_STATIS`: Kode QRIS statis untuk top up otomatis.
    - `WEBHOOK_URL`, `WEBHOOK_PORT`: Untuk endpoint webhook (jika menggunakan fitur webhook).
- File database (`botdata.db`) akan otomatis dibuat saat pertama kali bot dijalankan.
- File log error: `bot_error.log`

---

## Tips

- Untuk run di VPS/Cloud, gunakan `screen` atau `tmux` agar bot tetap berjalan di background.
- Jika ingin run sebagai service di Linux, Anda bisa membuat file service systemd.

---

## Troubleshooting

- Jika error "config.json tidak ditemukan", pastikan sudah rename dan isi dengan benar.
- Jika error library/module, ulangi install dependencies dengan `pip install -r requirements.txt`.
- Untuk environment selain Linux, penyesuaian manual mungkin diperlukan (misal Windows: pakai `venv\Scripts\activate`).

---

## License

MIT, Copyright © amifistore
    - `BASE_URL`, `API_KEY`, `BASE_URL_AKRAB`: URL/API dari provider produk Anda.
    - `QRIS_STATIS`: Kode QRIS statis untuk top up otomatis.
    - `WEBHOOK_URL`, `WEBHOOK_PORT`: Untuk endpoint webhook (jika pakai).
- File database (`botdata.db`) akan otomatis dibuat.
- File log error: `bot_error.log`

## Tips

- Untuk run di VPS/Cloud, gunakan `screen` atau `tmux` agar bot tetap berjalan di background.
- Jika ingin run sebagai service di Linux, buat file service systemd (bisa dibuatkan jika diminta).

## Troubleshooting

- Jika error "config.json tidak ditemukan", pastikan sudah rename dan isi dengan benar.
- Jika error library, ulangi install dependencies.
- Untuk environment selain Linux, penyesuaian manual mungkin diperlukan (misal Windows: pakai `venv\Scripts\activate`).

---
