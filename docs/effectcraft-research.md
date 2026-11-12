# Riset EffectCraft — temuan sebelum menulis kode

Sumber: repo `storytold/effectcraft` pada tag rilis **v0.24.1** (clone `main`, `docs/agents.md`,
`docs/control-protocol.md`, `README.md`) **dan kode sumber engine** (`crates/engine/src/cmd/*`,
`crates/effects/src/*`, `apps/effectcraft-cli/src/main.rs`). Semua command, id parameter, dan
format nilai di bawah diambil dari sumber tersebut — tidak ada yang dikarang.

> Catatan kejujuran: di lingkungan kerja ini **tidak ada** binary EffectCraft, toolchain Rust,
> maupun Docker, jadi `effectcraft-cli --help` tidak bisa dijalankan di sini. Karena itu daftar
> command diambil dari tabel `CommandSpec` di kode (yang menjadi isi `effectcraft-cli exec --list`)
> dan dari `USAGE` di `apps/effectcraft-cli/src/main.rs`. Konsekuensinya semua eksekusi nyata
> EffectCraft **belum terverifikasi di sini** — lihat "Yang belum bisa diverifikasi".

## 1. Tiga jalur kontrol

| Jalur | Perintah | Butuh jendela | Dipakai aplikasi ini |
|---|---|---|---|
| CLI headless | `effectcraft-cli run/exec/render …` | tidak | **ya** (mode Lokal & Docker) |
| Control channel | `effectcraft --control 9877`, JSON per baris di `127.0.0.1` | ya | opsional (mode Live) |
| MCP | `effectcraft-cli mcp [--bridge 9877]` | tidak / ya | tidak (tidak perlu di sini) |

### CLI (headless)

`effectcraft-cli <info|commands|exec|run|props|get|set|render-frame|render|script|replay|mcp> …`

Opsi umum: `--project F.ecproj | --demo | --empty`, `--save`, `--save-as F`, `--json`,
`--bridge PORT`. Error JSON ke stdout + exit 1; usage error exit 2.

Yang dipakai pipeline:

```sh
# 1) Membangun proyek dari daftar langkah (JSON array {command, params})
effectcraft-cli run --commands steps.json --empty --save-as project.ecproj --json

# 2) Render ke MP4 (H.264 murni Rust, tanpa FFmpeg)
effectcraft-cli render project.ecproj --comp Main --out render.mp4 \
  --format h264 --fps 30 --resolution full --progress --json

# 3) Cek pemasangan
effectcraft-cli info --empty --json          # {version, commands, effects, project, activeComp}
effectcraft-cli render-frame project.ecproj --time 1 --max-side 640 --out f.png --json
```

`run` berhenti di langkah pertama yang gagal dan pesannya berakhiran `(step N)` — ini yang dipakai
untuk memberi umpan balik ke LLM. `--commands F` menerima JSON array `{"command": ID, "params": {}}`,
atau JSON Lines; `--commands -` membaca stdin.

Lokasi binary bawaan installer Windows (menurut `docs/agents.md`):
`%LOCALAPPDATA%\Programs\ArtCraft\EffectCraft\effectcraft-cli.exe` (default per-user),
`C:\Program Files\ArtCraft\EffectCraft\effectcraft-cli.exe` (all-users), atau folder portable zip.

### Control channel

TCP `127.0.0.1:<port>`, satu objek JSON per baris, request/reply:

```json
{"id":1,"method":"engine.execute","params":{"command":"comp.new","params":{"name":"Main"}}}
{"id":1,"ok":true,"result":{"comp":1}}
```

Method lain yang relevan: `engine.commands`, `ui.*`, `render.frame`, `app.quit`, dan setiap engine
command lewat `engine.execute` (timeout 60 s per request, tanpa autentikasi, hanya 127.0.0.1).

### MCP

`effectcraft-cli mcp` (stdio, JSON-RPC). Tidak dipakai: CLI sudah cukup dan lebih mudah di-debug.

## 2. Command yang dipakai (whitelist)

Parameter diambil verbatim dari `CommandSpec.params` di sumber.

| Command | Parameter yang sah (ringkas) |
|---|---|
| `comp.new` | `{name?, width?, height?, frameRate?, duration? (s), startTime?, background? #hex, pixelAspect?, renderer?, open?}` → `{comp}` |
| `layer.newText` | `{text?, name?, position? [x,y], box? [x,y,w,h], font?, style?, size?, fill?, stroke?, justify?, tracking?, …}` → `{layer}` |
| `layer.newSolid` | `{name?, color? #hex, width?, height?}` → `{layer}` |
| `layer.newShape` | `{kind?: rect\|rounded\|ellipse\|star\|polygon\|none, name?, size?, fill?, stroke?, strokeWidth?, position?}` → `{layer}` |
| `effect.apply` | `{effect: id\|name, layers? (atau `layer`)}` → `{effects: [uid], paths: ["effects/#1"], effect}` |
| `prop.set` | `{layer?, path\|prop, value, time? (layer s), timeBase?: layer\|comp}` |
| `prop.addKey` | `{layer?, path\|prop, time? (layer s), timeBase?: layer\|comp, value?}` → jumlah key |
| `keys.select` | `{keys: [{layer, prop\|path, time}], timeBase?: layer\|comp, add?, toggle?}` |
| `keys.easyEase` | `{which?: both\|in\|out}` — berlaku pada key yang sedang terpilih |
| `keys.interpolation` | `{interpolation?: linear\|bezier\|continuousBezier\|autoBezier\|hold, …}` |
| `layer.timing` | `{layers?, start?, in?, out?, …}` (detik komposisi) |
| `file.save` | `{path?}` |
| `render.frame` | `{comp?, time?, max_side?, path?, base64?}` |

Catatan penting yang memengaruhi penerjemah:

- **Waktu keyframe default = waktu layer**, bukan waktu komposisi. Penerjemah selalu mengirim
  `timeBase: "comp"` supaya tidak salah saat layer di-trim.
- `prop.set`/`prop.addKey` menerima warna sebagai string `"#rrggbb"` (lihat
  `Value::coerce_json` di `crates/keyframe/src/value.rs`).
- `layer.timing` dengan `in`/`out` **memotong** layer tanpa menggeser `start_time`, jadi key
  pada waktu komposisi tetap sejajar.
- `effect.apply` mengembalikan `paths` seperti `effects/#1`; efek ke-N pada satu layer dapat
  dialamatkan `effects/#N/<param>`.
- Efek **hanya bisa** dipasang ke layer yang punya grup `effects` (solid/teks/shape/footage);
  layer null/kamera tidak.
- Beberapa command bersifat UI-only (`tool.*`, `view.*`, `timeline.*`) — tidak dipakai sama sekali.

## 3. Properti transform

Path yang dipakai (dikonfirmasi di `crates/project/src/tests.rs`):

- `transform/position` → `[x, y]` (piksel komposisi, titik anchor di tengah layer)
- `transform/scale` → `[x, y]` persen
- `transform/rotation` → derajat
- `transform/opacity` → 0–100
- `transform/anchor` → `[x, y]`

Layer baru (solid/teks/shape) default berposisi di tengah komposisi; teks default font bundel
`Inter`, ukuran 72, rata tengah, nama layer mengikuti teks.

## 4. Efek yang dipakai (nama & parameter terverifikasi dari `crates/effects/src`)

| Efek | Parameter (id: tipe) |
|---|---|
| **Gradient Ramp** (`ec.generate.gradientramp`) | `start`: point px, `startColor`: color, `end`: point px, `endColor`: color, `shape`: 0=Linear/1=Radial, `scatter`: number, `blend`: % |
| **4-Color Gradient** (`ec.generate.fourcolor`) | `positionsColors/point1..4`: point px, `…/color1..4`: color, `blend`, `jitter`, `opacity` |
| **Tint** (`ec.color.tint`) | `black` color, `white` color, `amount` % |
| **Brightness & Contrast** | `brightness` −150…150, `contrast`, `useLegacy` bool |
| **Hue/Saturation** | `hue` derajat, `saturation` %, `lightness` %, `channelControl` enum |
| **Glow** (`ec.stylize.glow`) | `based` 0=Alpha/1=Color, `threshold` %, `radius` px, `intensity`, `operation`, `glowOperation`, `glowDimensions` |
| **Drop Shadow** | `color`, `opacity` %, `direction` derajat, `distance` px, `softness` px, `shadowOnly` bool |
| **Gaussian Blur** | `blurriness` px, `dimensions` enum, `repeatEdge` bool |
| **Fast Box Blur** | `radius`, `iterations`, `dimensions`, `repeatEdge` |
| **Linear Wipe** | `completion` %, `angle` derajat, `feather` px |
| **Radial Wipe** | `completion` %, `startAngle`, `center` point px, `wipe` enum, `feather` |
| **Venetian Blinds** | `completion` %, `direction`, `width`, `feather` |
| **Invert** | `channel` enum, `blend` % |
| **Mosaic** | `horizontal`, `vertical`, `sharpColors` |
| **Noise** (`ec.noise.noise`) | `amount` %, `color` bool |
| **Fill** (`ec.generate.fill`) | `color`, `opacity`, `horizontalFeather`, `verticalFeather` |
| **Grid / Checkerboard / Circle** | `width`, `height`, `border`/`color`, `opacity`, `corner`/`center`, `invertGrid`, … |
| **Posterize / Threshold** | `level` |
| **Directional Blur / Radial Blur / Sharpen / Unsharp Mask / Emboss / Find Edges** | sesuai tabel di `whitelist.py` |

Koordinat titik efek adalah **piksel ruang layer/efek** (`Buf::to_px` memakai `scale` render,
bukan ukuran layer). Untuk solid seukuran komposisi, `[0,0]` = kiri atas. Rencana JSON memakai
titik **ternormalisasi 0–1** agar ramah-LLM, lalu penerjemah mengalikannya dengan ukuran layer.
Ini keputusan desain kami dan didokumentasikan di plan schema.

## 5. Render

`renderQueue` mendukung H.264 MP4, ProRes MOV, HEVC, AV1, WebM/VP9, PNG/JPEG/TIFF/EXR/TGA,
GIF, WAV/AIFF. Encoder murni Rust — **tidak ada FFmpeg** di dalam EffectCraft.

```sh
effectcraft-cli render main.ecproj --comp Main --out main.mp4 --format h264 \
  --fps 30 --resolution full --quality best --progress --json
```

`--resolution` menerima `full|half|third|quarter|<angka skala>`; `--start/--end` (detik) atau
`--work-area`; `--progress` menulis baris `progress <done> <total> <elapsed> <remaining>` ke stderr.

## 6. Docker

- Repo EffectCraft **tidak berisi Dockerfile** dan tidak menyebut `ghcr.io/storytold/effectcraft`
  sama sekali (dicari di seluruh checkout). Image yang disebut di brief tidak dapat saya
  verifikasi dari sini (host `ghcr.io` di luar jangkauan jaringan sandbox).
- Karena itu mode Docker di aplikasi ini:
  1. memakai nama image yang bisa diatur (default `ghcr.io/storytold/effectcraft:latest`),
  2. memberi preflight yang jelas bila image tidak ada / Docker tidak jalan,
  3. menyertakan `docker/Dockerfile` buatan kami yang mengunduh rilis Linux resmi EffectCraft dan
     memasang `effectcraft-cli` di `PATH`, sehingga pengguna punya image yang pasti bekerja.
- Mount: folder proyek → `/work`, command dijalankan `docker run --rm -v <proj>:/work -w /work <image> effectcraft-cli …`.

## 7. Batasan yang harus disebut jujur

1. **Tidak ada `effectcraft-cli.exe`/`effectcraft.exe` resmi untuk Windows di sandbox ini**, dan
   aset rilis GitHub (`release-assets.githubusercontent.com`) tidak bisa diunduh dari sini. Maka:
   - Semua kode jalur nyata (Lokal/Docker/Live) ditulis terhadap kontrak di atas.
   - Demo end-to-end di repo ini dihasilkan oleh **mesin simulator** bawaan aplikasi
     (`runner/simulator.py`), yang mengonsumsi urutan command yang sama dan merender MP4 dengan
     Pillow + FFmpeg (lewat paket `imageio-ffmpeg`). Label "SIMULATOR" selalu tampil di UI/log,
     dan file demo diberi nama jelas. Ini **bukan** keluaran EffectCraft.
   - Skrip `scripts/verify_with_effectcraft.py` menjalankan ulang rencana & langkah yang sama
     terhadap EffectCraft asli di mesin pengguna dan membandingkan hasilnya.
2. **GUI belum pernah dijalankan di sandbox** (tidak ada Tk/CustomTkinter, tidak ada display).
   Logika non-UI (validator, penerjemah, whitelist, pipeline, storage, kredensial, simulator)
   diuji dengan pytest.
3. **Preview video di dalam aplikasi** memakai poster frame + pemutar bawaan Windows
   (`os.startfile`), bukan embedded player. Alasannya: Tk tidak punya dekoder video, dan
   menambahkan VLC/libmpv membuat satu-file .exe membengkak. Slot untuk `python-vlc` disediakan
   bila pengguna memasangnya.
4. Control channel punya timeout 60 s per request, jadi render panjang tetap lewat CLI.
5. Windows Credential Manager dipakai lewat `ctypes` (`advapi32`), bukan `keyring`, supaya .exe
   tidak butuh dependensi biner tambahan.
