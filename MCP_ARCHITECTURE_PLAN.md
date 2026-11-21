# MCP IDX Mandiri — Audit dan Rencana Arsitektur

**Tanggal audit:** 21 November 2026  
**Ruang lingkup:** pemeriksaan statis repository workspace `D:\SAHAM\MCP`; tidak menghubungi provider, endpoint, atau layanan produksi.

## 1. Executive summary

Repository memuat 26 tool dalam `src/server.py`, tetapi `src/server_http.py` hanya mendaftarkan 14. Kedua transport mengulang registry, routing, logging, dan penanganan error secara terpisah. Sumber data yang tampak adalah Yahoo Finance/yfinance serta JSON lokal untuk pencarian ticker. Sejumlah tool fundamentals/flow mengakses yfinance secara langsung, melewati wrapper bersama. Tidak ditemukan adapter provider alternatif yang dapat diverifikasi.

Foreign flow merupakan proxy dari OHLCV, bukan data net foreign BEI. Tape reading juga memakai proxy harga-volume, bukan order book atau transaksi tick. Cache berupa `TTLCache` in-memory per proses. Tool VWAP dan gap meminta kategori `realtime` yang tidak terdaftar di cache. Tidak ada invalidasi aksi korporasi, persistent/shared cache, ataupun single-flight.

Screening engine **belum terverifikasi dalam workspace**: daftar file tidak berisi modul screening; README hanya menyebut `stock_screener.py` pada diagram struktur. Integrasi dan empat strategi yang disebutkan belum dapat diaudit.

Rancangan tujuan: registry/dispatcher tunggal bagi semua transport; domain service lepas dari kontrak MCP; provider adapter dengan provenance dan validasi; cache abstraction; screening sebagai salah satu modul opsional di samping data, teknikal, fundamental, pasar, portfolio, trading, dan riset.

Audit tidak menemukan bukti perubahan sumber; `git status` tidak tersedia karena executable `git` tidak ada di PATH. Tidak ada endpoint/produksi dihubungi dan tidak ada deployment.

## 2. Inventaris 26 tools dan temuan per tool

Semua tool berikut ada dalam daftar stdio (`src/server.py`). Input adalah parameter utama schema; ticker dimaksudkan sebagai simbol IDX, dengan `.JK` ditambahkan wrapper Yahoo. Output diuraikan dari implementasi aktual.

| # | Tool | Input utama | Fungsi/output dan temuan aktual |
|---|---|---|---|
| 1 | `get_stock_price` (`src/tools/price.py`) | `ticker` wajib | Via `YahooFinanceClient`: harga, previous close, perubahan, O/H/L, volume, kapitalisasi, timestamp retrieval, status market. Memerlukan `regularMarketPrice` walau fallback `currentPrice` dipakai sesudahnya; bisa menolak data yang sebenarnya ada. `market_status` hanya memeriksa `marketState == REGULAR`. Timestamp adalah waktu lokal retrieval, bukan timestamp quote. Error dipetakan ke exception domain. |
| 2 | `get_stock_info` (`info.py`) | `ticker` wajib | Profil, sektor/industri, deskripsi, kapitalisasi, sebagian rasio/dividen, rentang harga 52 minggu dan rerata 50/200 hari. Cache 24 jam. Client membuat tiga request history tambahan. Field Yahoo boleh kosong; sanitasi heuristik mengubah nilai ekstrem menjadi null. Sebagian error berupa dict legacy. |
| 3 | `get_historical_data` (`historical.py`) | `ticker`, `period`, `interval` | OHLCV dan data point lewat client Yahoo. Validator interval umum hanya menerima 1d/1wk/1mo, padahal client punya cache class intraday. Tidak ada validasi candle/tanggal umum pada boundary. Cache harian/intraday. |
| 4 | `get_technical_indicators` (`indicators.py`) | `ticker`, `indicators`, `period` | RSI, MACD, SMA/EMA, Bollinger, stochastic, ATR, OBV, VWAP, ADX, Ichimoku dihitung dari OHLCV. Perlu sinkronisasi schema dengan validator, pemeriksaan minimum bar per indikator dan status hasil parsial. |
| 5 | `get_fibonacci_levels` (`fibonacci.py`) | `ticker`, `period`, `trend` | Deteksi swing dan level retracement/extension serta insight/support-resistance. Pivot adalah heuristik dan baru terkonfirmasi setelah bar kanan ada. Perlu status data cukup dan provenance. |
| 6 | `get_ma_crossovers` (`ma_crossover.py`) | `ticker`, `period`, `lookback_days` | Crossover SMA/EMA, jarak MA dan rating sinyal. Heuristik dari harga harian; makna waktu sesi dan periode perlu eksplisit. Rating bukan rekomendasi investasi. |
| 7 | `get_candlestick_patterns` (`candlestick.py`) | `ticker`, `period`, `lookback_days` | Deteksi pola candle, konteks tren/volume dan validity score. Score bukan probabilitas terkalibrasi atau success rate terbukti. Jalur error dict ada; perlu candle valid dan data cukup. |
| 8 | `get_financial_ratios` (`financial_ratios.py`) | `ticker` | Rasio valuasi/profitabilitas/leverage/likuiditas dan growth dari info/laporan Yahoo dengan fallback kalkulasi. Cache 24 jam. Batas sanitasi tetap dapat mengubah angka menjadi null; fiscal date, unit, dan makna null perlu ikut hasil. |
| 9 | `get_volume_analysis` (`volume_analysis.py`) | `ticker`, `period` | Rerata volume, spike/rasio, trend dan korelasi volume-harga dari OHLCV. Nilai periode seperti 7d/30d harus dipetakan, bukan semuanya valid sebagai periode Yahoo. Volume nol dan sesi tidak lengkap perlu dibedakan. |
| 10 | `get_volatility_analysis` (`volatility_analysis.py`) | `ticker`, `period` | Historical volatility, beta terhadap IHSG, ATR/risk level. Beta butuh tanggal kedua seri sejajar; periode annualisasi dan asumsi perlu tercantum. Missing bar dapat mendistorsi hasil. |
| 11 | `search_stocks` (`search.py`) | `query`, `limit`, `sector` opsional | Pencarian lokal nama/kode/sektor dari JSON ticker. Bukan pencarian live. Kegagalan membaca file diturunkan menjadi daftar kosong, tak terbedakan dari nol hasil; snapshot dapat usang. |
| 12 | `get_market_summary` (`market.py`) | `include_movers`, `movers_limit` | IHSG (`^JKSE`), status dan top movers dari universe ticker lokal/Yahoo. Potensi request serial dalam jumlah besar. Status berbasis jam kerja sederhana tanpa kalender libur/sesi. Cache `market` tersedia tetapi pemakaian efektif perlu disatukan. |
| 13 | `compare_stocks` (`compare.py`) | `tickers`, `period`, `metrics` | Kinerja historis dan metrik perbandingan. Maksimum daftar 20; request serial. Helper dapat meredam error menjadi `{}` sehingga kegagalan parsial perlu dilaporkan. `metrics` harus tervalidasi. |
| 14 | `get_watchlist_prices` (`watchlist.py`) | `tickers` | Harga ringkas banyak ticker; client serial dan melewati ticker gagal. Validator membatasi 20, tetapi output hanya ticker sukses, tanpa daftar gagal; hasil berpotensi dikira lengkap. Cache harga per ticker. |
| 15 | `get_foreign_flow` (`foreign_flow.py`) | `ticker`, `period` | Proxy aliran/akumulasi dari harga-volume. Deskripsi dan kode menyatakan bukan net foreign BEI. Memanggil yfinance langsung; sebagian error dict. Label proxy harus dijaga. |
| 16 | `get_bandarmology` (`foreign_flow.py`) | `ticker`, `period` | Fase akumulasi/markup/distribusi/markdown dari OHLCV, termasuk perlakuan tick/ARA/ARB. Bukan data broker/investor. Status FCA/PPK tidak terbukti diperoleh dinamis; aturan bursa perlu versi/tanggal berlaku. |
| 17 | `get_tape_reading` (`foreign_flow.py`) | `ticker`, `period` | Tekanan beli/jual diproksikan dari harga-volume. Bukan order book, broker flow atau transaksi tick; resolusi dan keterlambatan Yahoo membatasi interpretasi. |
| 18 | `get_financial_statements` (`fundamental.py`) | `ticker` | Analisis income statement, balance sheet, cash flow, margin/health score dari yfinance langsung. Kolom/laporan emiten dapat kosong/bervariasi; score perlu komponennya dan tanggal fiskal. Beberapa error dict. |
| 19 | `get_earnings_growth` (`fundamental.py`) | `ticker` | Growth earnings/revenue YoY, CAGR/rating dari laporan yfinance langsung. Jumlah periode tak pasti; CAGR harus menangani nilai nol/negatif dan fiscal year; hasil butuh basis waktu. |
| 20 | `get_analyst_ratings` (`fundamental.py`) | `ticker` | Consensus/rekomendasi, estimasi dan calendar bila Yahoo menyediakannya. Cakupan emiten BEI tidak dijamin; bedakan unavailable dari neutral/no rating dan sertakan timestamp. |
| 21 | `get_dividend_history` (`fundamental.py`) | `ticker` | Riwayat dividen dari Yahoo. Bukan kalender aksi korporasi BEI lengkap; split adjustment, mata uang, ex-date dan payment date memerlukan sumber/validasi khusus. |
| 22 | `get_breakout_detection` (`breakout.py`) | `ticker`, `lookback`, `period`, `volume_threshold` | Konsolidasi, breakout, konfirmasi volume, target/stop dan false-breakout warning dari Yahoo OHLCV. Heuristik, bukan prediksi terkalibrasi. Parameter numerik perlu batas positif; bar terbaru dapat belum final. |
| 23 | `get_divergence_detection` (`divergence.py`) | `ticker`, `indicators`, `lookback`, `period` | Divergensi regular/hidden pada RSI/MACD/OBV dan sinyal gabungan. Pivot memerlukan bar konfirmasi dan rentan false positives; validasi indikator/lookback diperlukan. |
| 24 | `get_vwap` (`intraday.py`) | `ticker`, `period`, `include_bands` | VWAP/band dihitung dari OHLCV yang tersedia. Candle-based, bukan tick-level; reset per sesi perlu dipastikan. Meminta cache kategori `realtime`, yang tidak didefinisikan sehingga cache no-op. |
| 25 | `get_pivot_points` (`intraday.py`) | `ticker`, `pivot_type` | Standard/Fibonacci/Woodie/Camarilla dari harga OHLC sebelumnya. Basis “sesi sebelumnya” harus jelas; pembulatan tidak otomatis mengikuti fraksi harga IDX. |
| 26 | `get_gap_analysis` (`intraday.py`) | `ticker` | Gap previous close ke open terakhir dan analisisnya. Memakai dua bar terakhir data 5 hari; sebelum sesi berjalan bar terakhir bukan sesi saat ini. Meminta cache `realtime` yang tak terdaftar. |

### Validasi dan error lintas tool

- `src/utils/validators.py`: ticker hanya uppercase/non-empty (tidak membuktikan listing BEI); period, interval, indikator dan daftar maksimum 20 divalidasi sebagian. Daftar ticker dibersihkan setelah batas panjang awal dan daftar kosong hasil pembersihan perlu ditolak eksplisit.
- Banyak schema tidak membatasi properti tambahan; batas numerik sering hanya deskripsi. Handler berbeda: exception domain, error dict, atau fungsi sinkron tanpa validasi seragam.
- Stdio mengubah legacy error dict menjadi exception; HTTP mengirimkannya sebagai JSON. Catch-all HTTP memetakan semua exception ke `NETWORK_ERROR`, termasuk kesalahan parameter/program.
- Fungsi yfinance sinkron dipanggil dari `async def`; ini dapat memblokir event loop. Retry/backoff konsisten tidak ditemukan.
- Output tidak memiliki envelope umum `source`, `retrieved_at`, `market_as_of`, `is_delayed`, `warnings`, `errors`; kosong, stale, unsupported dan gagal sulit dibedakan.

## 3. Temuan arsitektur MCP

- `src/server.py` mendaftarkan dan dispatch 26 tool untuk stdio. `src/server_http.py` mendaftarkan 14; 12 tool tidak tersedia di HTTP: tiga flow, empat fundamental, breakout, divergence dan tiga intraday.
- Root HTTP menyatakan jumlah `tools: 14` secara hardcode. Registry dapat drift dari angka itu.
- HTTP punya CORS `allow_origins=["*"]` dengan credentials aktif, host default `0.0.0.0`, dan endpoint call/batch custom. Berisiko jika terekspos remote tanpa kontrol akses. Tidak ada perubahan/inspeksi deployment.
- Kedua transport menggandakan registry, router, logging, error conversion. `src/tools/__init__.py` kosong; tidak ada registry bersama.
- Tool files mencampur schema, handler, kalkulasi dan akses provider. `foreign_flow.py` berisi tiga tool; `fundamental.py` empat analisis. Sejumlah jalur akses yfinance langsung melewati wrapper.
- `Settings` memiliki `YAHOO_TIMEOUT`, `RATE_LIMIT_*`, `MAX_HISTORY_PERIOD`, tetapi pemakaian efektifnya tidak terlihat pada jalur yang diperiksa. Env integer tidak divalidasi range.
- Logging stdio ke stderr dan file; HTTP ke stdout dan file. Konfigurasi pada import dapat berbenturan. Argumen tool dicatat utuh.

## 4. Data provider

Provider yang dapat dibuktikan: Yahoo Finance melalui yfinance untuk harga/history/info/laporan/dividen/estimasi; JSON lokal untuk search/universe. Tidak ada adapter kedua atau konektor resmi BEI yang ditemukan. Ketersediaan provider alternatif **BELUM TERVERIFIKASI**.

`YahooFinanceClient` menambahkan `.JK`, membungkus quote/history/info dan melakukan sanitasi rasio. Atribut timeout diinisialisasi tetapi tidak diteruskan secara nyata pada pemanggilan yfinance yang tampak. `fundamental.py` dan `foreign_flow.py` membuat objek `yf.Ticker` sendiri. Belum ada fallback provider. Timestamp histori hanya tanggal, tanpa waktu/zona sesi; timestamp quote adalah waktu proses, bukan waktu quote dari sumber.

Rekomendasi: protokol `MarketDataProvider` dan `FundamentalsProvider`; pertahankan Yahoo sebagai adapter awal. Adapter baru hanya setelah coverage, hak akses, latency, timestamp, unit, dan kebijakan penggunaan diverifikasi. Fallback harus eksplisit menyebut sumber tiap field, tanpa pencampuran diam-diam.

## 5. Cache dan performa

| Cache | TTL | Temuan |
|---|---:|---|
| price | 60 dtk | Quote; batch memakai cache per ticker. |
| historical_intraday | 300 dtk | Dalam memori per proses. |
| historical_daily | 3600 dtk | Bar harian terakhir mungkin belum final. |
| info | 86400 dtk | Field profil dan history punya freshness berbeda. |
| search | 21600 dtk | Perlu invalidasi saat JSON universe berubah. |
| market | 60 dtk | Penggunaan aktual perlu disatukan. |
| financial_ratios | 86400 dtk | Perlu fiscal period/version dalam semantik cache. |

`CacheManager` menggunakan `cachetools.TTLCache`, maxsize default 1000 per kategori. Cache hilang saat restart dan tiap worker punya cache sendiri; tidak ada statistik hit/miss, invalidasi spesifik, single-flight atau shared backend. Key berupa string gabungan. Tipe `realtime` yang diminta VWAP/gap tak terdaftar. Akses yfinance langsung menghindari cache terpusat. Klasifikasikan TTL quote, bar intraday provisional, daily finalized, fundamental per fiscal period, metadata dan universe sebelum mengubah TTL.

## 6. Kualitas data dan keandalan

- Wrapper OHLCV hanya membentuk angka/tanggal; tidak ditemukan validasi umum `low <= open/close <= high`, harga positif, volume nonnegatif, timestamp duplikat, urutan sesi, missing bars, adjustment, currency/unit atau kelengkapan bar terakhir.
- History yfinance diringkas jadi tanggal saja, menghilangkan waktu/zona. Keselarasan tanggal saham dan IHSG untuk beta/comparison belum dipaksakan.
- Basis harga adjusted/unadjusted tidak dinyatakan konsisten.
- Market hours adalah hari kerja 09:00–16:00 WIB, tanpa kalender hari libur/sesi. Definisi Yahoo `marketState` berbeda.
- Error kosong/parsial bisa berubah jadi `{}` atau dict; watchlist membuang gagal ticker. Analisis dari data kurang lengkap berisiko dianggap sah.
- Retry/backoff/circuit breaker, health/metrics provider, cache hit rate, latency provider dan correlation id tidak terlihat.

## 7. Screening engine

Pemeriksaan file aktual tidak menemukan implementasi. Hanya `README.md` menyebut `stock_screener.py` dalam diagram. Kemungkinan engine berada di luar checkout atau tidak ikut workspace. Empat strategi, interface, dependensi, dan tes: **BELUM TERVERIFIKASI**.

Integrasikan nanti sebagai modul analitik opsional yang mengonsumsi kontrak provider/data ternormalisasi dan mengembalikan kandidat beserta kriteria, universe, timestamp, coverage, warning. Jangan mengubah atau membangun ulang engine, dan jangan menebak API sebelum artefak asli tersedia. MCP tetap infrastruktur umum.

## 8. Rekomendasi perbaikan

### P0 — fondasi

1. Satu registry kanonis (metadata, schema, handler, kategori) untuk semua transport; jaga nama/semantik 26 tool dengan adapter kompatibilitas.
2. Error envelope stabil untuk validasi, unavailable, provider/timeout, internal; hentikan pemetaan semua error ke NETWORK_ERROR.
3. Satukan akses data melalui provider adapter tanpa mengubah bentuk keluaran selama tahap migrasi.
4. Validasi data dan provenance/freshness sebelum analisis; tandai hasil invalid/parsial secara eksplisit.
5. Hilangkan angka tool hardcode; parity list/call semua transport dari registry.

### P1 — keandalan/performa

6. Offload I/O sinkron ke threadpool atau adapter async; tegakkan timeout, retry terbatas, backoff dan rate limit.
7. Gunakan tipe cache terdefinisi; tambahkan invalidasi, metrics, single-flight; shared cache bila multi-worker memang diperlukan.
8. Validasi kalender/sesi dan periode; jangan mengklaim realtime tanpa timestamp sumber/lag.
9. Bedakan unavailable, neutral, parsial dan empty; tampilkan setiap kegagalan batch.

### P2 — pengembangan umum BEI

10. Verifikasi provider sebelum memilih; prioritaskan instrument master/universe, kalender, aksi korporasi, sektor dan fundamental yang bersumber jelas.
11. Tambahkan modul sektor/pasar, portfolio, riset/evaluasi berdasar kebutuhan. Screening existing tetap opsional.

## 9. Rancangan arsitektur mandiri

```text
src/
  app/                 # composition root, lifecycle, settings
  transports/          # stdio, MCP HTTP; REST opsional
  registry/            # deklarasi tool dan dispatcher kanonis
  contracts/           # schema input/output dan error envelope
  domain/
    market_data/ fundamentals/ technical/ market/
    portfolio/ screening/ research/
  providers/            # interface dan adapter Yahoo/provider lain
  data_quality/         # normalisasi, validasi, provenance
  cache/                # interface, in-memory, shared backend
  observability/        # structured logs, metrics, tracing
```

Alur: transport → registry/dispatcher → validasi schema → service domain → provider → normalisasi/provenance → validasi kualitas → cache → hasil/error typed. Analitik memakai model kanonis dan tidak mengakses yfinance. Registry menjadi sumber daftar tool dan routing untuk tiap transport. Data provider tidak tercampur tanpa provenance.

## 10. Strategi mempertahankan 26 tools

- Bekukan snapshot nama, schema, default, semantik output/error sebelum migrasi.
- Implementasikan registry kanonis berisi 26 nama dari inventaris; pindahkan kalkulasi ke service bertahap, adapter kompatibilitas menjaga output lama.
- Stdio, HTTP dan REST convenience memakai dispatcher/service sama.
- Migrasi per kelompok dengan fixture deterministik/offline dan perbandingan bentuk hasil; jangan panggil provider live untuk pemeriksaan kontrak.
- Hapus jalur lama hanya setelah parity semua transport/consumer terbukti. Deployment terpisah dari audit ini.

## 11. Strategi integrasi screening

1. Dapatkan artefak asli, dependensi, empat strategi, universe, input/output dan asumsi sumber data.
2. Buat characterization tests tanpa mengubah logika, petakan konsumsi data ke model provider ternormalisasi.
3. Bungkus dengan adapter dalam `domain/screening`; jangan campurkan dengan transport atau analisis teknikal lain.
4. Hasil menyertakan waktu, universe, coverage dan kriteria; sajikan sebagai analisis kandidat.
5. Daftarkan tool opsional setelah parity dan schema disepakati. Tahap pertama belum dapat dilakukan karena kode tidak ditemukan.

## 12. Fitur masa depan menurut kategori

| Kategori | Peluang | Prasyarat/guardrail |
|---|---|---|
| Perbaikan fungsi saat ini | Error envelope, batch outcome, kalender, validasi, provenance, schema konsisten | Prioritas sebelum fitur baru. |
| Arsitektur/performa | Registry, provider adapters, async I/O, shared cache, rate limit, observability | Ukur bottleneck; internal service tidak harus jadi tool. |
| Data baru | Kalender BEI, emiten, corporate actions, index constituents, foreign flow riil | Verifikasi sumber/hak akses; jangan mengklaim Yahoo sebagai data resmi. |
| Teknikal | Pengayaan indikator/pola, multi-timeframe timestamp-aware | Skor heuristik bukan probabilitas. |
| Fundamental | Normalisasi lintas emiten/fiscal period, rasio adjusted, coverage | Cantumkan sumber, mata uang dan unit. |
| Pasar/sektor | Breadth, sektor, index composition/rotation | Universe dan klasifikasi terpercaya. |
| Portfolio/investasi | Return, risk, benchmark, alokasi, dividend cashflow | Holdings eksplisit; keputusan tetap di pengguna/ChatGPT. |
| Trading/monitoring | Alert, watchlist state, session-aware levels | Butuh scheduler/stream dan sumber tepat waktu. |
| Evaluasi/riset | Backtest, walk-forward, event study | Kendalikan look-ahead/survivorship, biaya dan slippage. |

## 13. Prioritas dampak dan risiko

| Urutan | Pekerjaan | Dampak | Risiko bila ditunda | Kompleksitas |
|---:|---|---|---|---|
| 1 | Registry/dispatcher tunggal dan parity 26 tool | Tinggi | Tinggi: transport berbeda | Sedang |
| 2 | Provider boundary, provenance, validasi kualitas | Sangat tinggi | Sangat tinggi: data salah tak diketahui | Tinggi |
| 3 | Error contract, timeout, retry/rate limit, logging | Tinggi | Tinggi: hang/error menyesatkan | Sedang |
| 4 | Cache TTL/invalidation/metrics | Tinggi | Sedang-tinggi: stale/duplikasi request | Sedang |
| 5 | Audit dan adapter screening existing | Sedang | Sedang: duplikasi/ketergantungan tersembunyi | Sedang; menunggu artefak |
| 6 | Provider alternatif dan data BEI | Tinggi | Tinggi bila perlu data resmi/live | Tinggi/vendor-dependent |
| 7 | Modul kemampuan baru | Variatif | Rendah-sedang | Variatif |

## 14. Roadmap implementasi bertahap

Estimasi kasar satu engineer berpengalaman; tidak termasuk pengadaan vendor.

| Tahap | Hasil | Estimasi | Kompleksitas |
|---|---|---:|---|
| 0. Discovery screening/kontrak | Temukan engine, kontrak dan fixture 26 tool | 2–4 hari setelah artefak tersedia | Rendah-sedang |
| 1. Fondasi kontrak | Registry, dispatcher, error envelope, config tervalidasi | 1–2 minggu | Sedang-tinggi |
| 2. Provider/quality | Adapter Yahoo, model kanonis, provenance, OHLCV/fundamental validation | 2–3 minggu | Tinggi |
| 3. Parity/reliability transport | stdio/HTTP konsisten, hardening, concurrency, timeout/retry/log | 1–2 minggu | Sedang-tinggi |
| 4. Cache/performa | TTL per data, invalidasi, single-flight, metrics/shared jika perlu | 1–2 minggu | Sedang |
| 5. Migrasi parity | Pindah 26 handler bertahap, validasi fixture offline | 2–4 minggu | Tinggi |
| 6. Screening adapter | Integrasi tanpa ubah strategi setelah audit engine | 3–7 hari setelah audit | Sedang |
| 7. Data/fungsi baru | Provider/aksi korporasi/sektor/portfolio berdasar sumber terverifikasi | 2–8+ minggu | Tinggi/variatif |

Hindari satu rilis migrasi besar; tahapan dapat tumpang tindih hanya setelah kontrak provider/registry stabil.

## 15. Strategi pengujian fase implementasi

Tidak ada tes dijalankan pada fase audit. Untuk implementasi: unit pure calculation dengan fixture sintetis; contract tests 26 tool pada dua transport; provider fixtures offline untuk data missing/stale/malformed/adjusted; parity output lama-baru; concurrency, timeout, retry, TTL/invalidation; property checks OHLCV/kalender; mock integration. Uji live provider hanya jika dibutuhkan dan risikonya jelas. Screening memakai snapshot diketahui dan pemeriksaan anti-lookahead.

## 16. Risiko migrasi dan rollback

- **Semantik/output:** contract snapshots dan adapter kompatibilitas; rilis per kelompok.
- **Provider berbeda:** shadow comparison terbatas, provenance, tanpa fallback diam-diam.
- **Data stale/invalid:** quality gate, warning eksplisit dan circuit breaker.
- **Shared cache:** versioned keys, TTL konservatif, invalidasi; switch kembali ke cache lokal/disabled.
- **Transport/security:** auth, CORS dan TLS/proxy sebelum eksposur; stdio tetap mandiri.
- **Rollback:** setiap tahap commit/rilis terpisah; pertahankan versi sebelumnya dan config switch ke dispatcher/provider lama. Uji berdampingan sebelum cutover. Tidak ada tindakan produksi dilakukan dalam audit.

## 17. Yang belum terverifikasi dan batas audit

- Engine screening dan empat strategi: **BELUM TERVERIFIKASI**; hanya referensi diagram README.
- Provider alternatif BEI, ketersediaan/izin: **BELUM TERVERIFIKASI**; tidak ada konektor yang ditemukan.
- Status/config/endpoint produksi atau Render: tidak diperiksa/dihubungi.
- Akurasi/coverage live tiap tool: tidak diuji lewat jaringan; temuan dari kode aktual.
- Audit statis tidak membuktikan semua perilaku runtime.
- Git tidak tersedia pada PATH sehingga status repository tidak dapat diperiksa dengan git. Audit hanya menulis dokumen ini; tidak ada kode sumber diubah. Tidak ada deployment atau panggilan endpoint produksi.

## Rekomendasi urutan fase berikutnya

Pertama, dapatkan artefak screening asli. Berikutnya bekukan kontrak 26 tool dan buat registry/dispatcher bersama. Lalu satukan provider dengan validasi/provenance; tegakkan parity transport dan reliability; migrasikan per kelompok memakai fixture offline. Tambahkan provider dan fitur baru hanya setelah sumber diverifikasi.
