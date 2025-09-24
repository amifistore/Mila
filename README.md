# Bot Akrab Step Inline Installer

## Cara Install

1. **Clone/source code** ke folder Anda.
2. **Copy** `config.json.example` ke `config.json` lalu isi semua field sesuai data bot Anda.
3. (Opsional) Aktifkan virtualenv:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
4. **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
    Atau cukup jalankan:
    ```bash
    bash install.sh
    ```
5. **Jalankan bot**:
    ```bash
    python bot_akrab_step_inline.py
    ```

## Konfigurasi

- **config.json** WAJIB diisi dengan benar (lihat config.json.example).
    - `TOKEN`: Token bot Telegram Anda.
    - `ADMIN_IDS`: List ID admin (angka, bisa diambil dari Telegram `id`).
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
