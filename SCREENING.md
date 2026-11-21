# Screening (v2)

Dua tool baru: `screen_stocks` (saring dari snapshot, tanpa jaringan) dan `screening_data` (status/refresh/presets).

Setup 5 kategori ada di `src/config/presets.json` (data, bukan kode). Ubah angka atau tambah setup di sana.
Kriteria ad hoc bisa dikirim lewat argumen `criteria`; fitur yang tersedia: `screening_data action=presets`.

## Langkah pakai
1. Universe: `python scripts/build_universe.py "<xlsx>" --as-of YYYY-MM-DD --expected-total N` (sudah dibuat dari xlsx 20 Nov 2026: 944 kode, 841 Utama+Pengembangan).
2. Snapshot: `python scripts/refresh_snapshot.py` (atau `screening_data action=refresh`), jalankan sekali setelah bursa tutup.
3. Panggil `screen_stocks`. Hasil dipaginasi (limit = ukuran halaman, lanjut dengan next_offset), memuat alasan lolos, cakupan, dan peringatan.

Catatan: value_est = close x volume Yahoo (estimasi). Ticker yang gagal diunduh dilaporkan, tidak dianggap "tanpa setup".
Tes: `python -m pytest tests/test_screening.py` (offline).

## Konfigurasi (server netral, tanpa strategi bawaan)
Server tidak mengandung strategi, fee, atau batas likuiditas pribadi. Semua itu ditentukan pemanggil (prompt) atau konfigurasi:
- Setup: `src/config/presets.json`, atau file lain lewat env `SCREENING_PRESETS_FILE`.
- Papan yang dipindai: env `SCREENING_BOARDS` (default `Utama,Pengembangan`).
- Likuiditas, harga minimum, sektor dsb.: argumen `filters` pada `screen_stocks` (default: tanpa filter).
- Backtest: `--fee`, `--min-value`, `--min-close` (default 0 = mentah).

## Cara pakai
Panggil tanpa argumen = daftar ticker yang sudah tersaring dari semua kategori (default). Opsional untuk menyempitkan: `presets` (kategori siap pakai, lihat `screening_data action=presets`), `criteria` (spesifikasi sendiri), `filters` (likuiditas, harga, papan, ...), `sort_by` (urutan baca). Tanpa presets/criteria = semua kategori (luas).
Kategori: EARLY_REVERSAL, HEALTHY_PULLBACK, BASE_CONSOLIDATION, PRE_BREAKOUT, BREAKOUT, TREND_CONTINUATION, MOMENTUM.
Setelah menambah fitur/preset baru, jalankan ulang `python scripts/refresh_snapshot.py` agar snapshot memuat fitur terbarunya (tool memberi peringatan bila snapshot lama).
Analisis: `scripts/backtest_setups.py` (hasil historis) dan `scripts/coverage_report.py` (cakupan & kebersihan).

## Cloud (Render)
- Start command: `python -m src.render_server`; Build: `pip install --prefer-binary -r requirements.txt`; env `IDX_MCP_API_KEY` (token Bearer), `PYTHON_VERSION`.
- `/health` publik (keepalive). `/admin/status` dan `/admin/refresh` (GET/POST) dilindungi Bearer yang sama.
- Snapshot dibuat ulang otomatis oleh server: saat kosong/parsial/lebih tua dari 3 hari, dan tiap hari kerja setelah 17:30 WIB. Jeda ulang 60 menit bila gagal. Matikan dengan `SCREENING_AUTO_REFRESH=false`.
- Disk Render gratis tidak permanen: setelah deploy/restart snapshot kosong dulu, lalu terbentuk sendiri (sekitar 10-25 menit; selama itu `screen_stocks` memberi pesan NO_SNAPSHOT).
