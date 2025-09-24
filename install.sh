#!/bin/bash
echo "=== Installer Bot Akrab Step Inline ==="
echo "Membuat virtualenv (opsional)..."
python3 -m venv venv
source venv/bin/activate

echo "Menginstall dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "=== INSTALASI SELESAI ==="
echo "- Silakan copy config.json.example menjadi config.json dan lengkapi isinya."
echo "- Untuk menjalankan bot:"
echo "  source venv/bin/activate"
echo "  python bot_akrab_step_inline.py"
echo ""
echo "File database (botdata.db) otomatis dibuat saat bot pertama kali dijalankan."
