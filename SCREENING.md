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

## Filter "bersih" (saham mati/sepi, default aktif)
Bukan strategi, hanya kebersihan data. Ticker dibuang otomatis bila salah satu terpenuhi (jumlahnya muncul di `coverage.dropped_as_dead` dan peringatan):
- Harga datar >= 10 dari 20 sesi (`SCREENING_CLEAN_MAX_FLAT_DAYS`).
- Volume nol >= 3 sesi (`SCREENING_CLEAN_MAX_ZERO_VOL_DAYS`).
- Rata-rata nilai transaksi 20 sesi < Rp1 miliar/hari (`SCREENING_CLEAN_MIN_AVG_VALUE`, default `1e9`).
- Nilai transaksi hari terakhir < Rp100 juta (`SCREENING_CLEAN_MIN_LAST_VALUE`, default `1e8`). Rata-rata 20 sesi bisa terdongkrak lonjakan lama sehingga saham yang kini hampir tak diperdagangkan tetap lolos; syarat ini menutup celah itu. Batas 100 juta adalah pilihan pragmatis (uji pada data 20 Nov 2026: hanya 3 dari 105 ticker terbuang, hasil sama untuk batas Rp50-100 juta), bukan hasil uji historis.

Setel batas ke `0` untuk menonaktifkan satu syarat, atau `clean=false` pada `screen_stocks` untuk semuanya. Filter eksplisit pemanggil pada `avg_value20_est` / `value_est` didahulukan atas batas bawaan yang bersangkutan.

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

## Level harga dan kalkulator R/R (tool terpisah, tidak mempengaruhi screener)

`screen_stocks` tidak berubah dan tidak memakai level apa pun untuk menyaring. Dua tool tambahan dipanggil per ticker setelah kandidat ada:

- `get_levels(ticker, pivot_bars=2, swing_count=5)`: angka mentah dari data harian (bukan harga live, jadi tersedia saat bursa tutup): swing high/low terkonfirmasi (pengapit `pivot_bars` bar kiri-kanan, beberapa terakhir dengan tanggal), ekstrem sementara dari bar yang belum bisa dikonfirmasi, low 5/10/20 hari, high 20/20-sebelumnya/60 hari, Fibonacci 38,2/50/61,8% dan extension 127,2/161,8% dari swing terakhir, pivot standar dari sesi terakhir, gap belum tertutup (60 sesi, minimal 0,3 ATR), dan `dist_atr` tiap level (negatif = di bawah close). Periksa `data.current` dan `data.last_bar_partial`. Tidak ada rekomendasi entry/SL/TP.
- `calc_risk_reward(entry, sl, tp, ...)`: R/R bersih setelah fee, slippage (tick BEI), lot dari batas risiko dan alokasi, dan `min_rr` untuk entry maksimal. Semua biaya dan batas berasal dari input; tidak ada nilai bawaan pribadi.
