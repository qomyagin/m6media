# m6media — Haval M6 (2023) uchun video konverter: AVI/XviD, AC3, USB

[![tests](https://github.com/qomyagin/m6media/actions/workflows/ci.yml/badge.svg)](https://github.com/qomyagin/m6media/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

**Til:** [Русский](README.md) · [English](README.en.md) · [Қазақша](README.kk.md) · Oʻzbekcha

> **Haval M6 fleshkadagi filmni koʻrmayaptimi, AVI/XviD yoki MKV (AC3)
> oʻynamayaptimi?** Koʻpincha muammo exFAT yoki fayl nomida emas, kodekda:
> M6 AVI konteynerini qoʻllab-quvvatlaydi, lekin MPEG-4 Part 2 (XviD/DivX)
> kodekini dekodlay olmaydi. `m6media` bunday fayllarni topadi, **faqat
> ularni** H.264/AAC MP4 ga oʻgiradi, ishlayotgan fayllarga tegmaydi.

Skript Haval M6 (M6 Plus, Rossiya nashri 2023–2026) multimedia tizimi uchun
video, musiqa va rasmlarni tayyorlaydi, nima uchun fayl koʻrinmasligini
tushuntiradi va **macOS, Linux hamda Windows** da ishlaydi.

Haqiqiy **exFAT fleshkada** tekshirildi: AVI/XviD koʻrinmadi, MKV/H.264
ishladi. Batafsil — «Nega Haval M6 AVI/XviD oʻynamaydi» boʻlimida.

Foydali havolalar: [FAQ](FAQ.uz.md) · [moslik jadvali](docs/COMPATIBILITY.md) · [English](README.en.md)

> Tarjima maʼlumot uchun berilgan. Eng soʻnggi versiya — [README.md](README.md).

---

## Tez-tez uchraydigan muammolar

| Belgi | Nimani tekshirish kerak |
|---|---|
| Haval M6 AVI ni koʻrmayapti | XviD/DivX/MPEG-4 Part 2 → H.264 ga oʻgirish |
| Video bor, ovoz yoʻq | AC3/E-AC3/DTS → AAC stereo |
| 4 GB dan katta fayl koʻchmayapti | FAT32 → exFAT yoki `--fat32 split` |
| Fleshka koʻrinmayapti | FAT32/exFAT, NTFS emas; boʻlinishni tekshirish |
| Baʼzi fayllar oʻynaydi, baʼzilari yoʻq | turli kodeklar; `--diagnose` |

Toʻliq tahlil: [FAQ.uz.md](FAQ.uz.md) va [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

---

## Skript nima qiladi

1. `ffprobe` orqali konteyner, kodeklar, oʻlcham, fps va ovozni aniqlaydi.
2. Faylni shunchaki qayta qadoqlash/koʻchirish yoki oʻgirish kerakligini
   hal qiladi. Mos fayl standart holatda **oʻtkazib yuboriladi** va chiqish
   papkasida takrorlanmaydi.
3. **Mos boʻlmagan** videoni maqsadli formatga keltiradi:
   * MP4 (`+faststart`, `mp42`) yoki `--container mkv`;
   * H.264 Main@4.0, 8 bit, 4:2:0 (`yuv420p`), 1920×1080 gacha,
     30 fps gacha, CRF 21 va bitrate chegarasi;
   * AAC-LC, 48 kHz, stereo, 192 kbit/s.
4. Mos boʻlmagan musiqani **MP3** (256 kbit/s, 44,1 kHz, stereo,
   ID3v2.3 + ID3v1) yoki AAC/M4A ga keltiradi. Mos MP3/WMA/AAC/FLAC/WAV/OGG
   fayllariga tegmaydi.
5. Mos boʻlmagan rasmlarni **JPEG** ga keltiradi (macOS da `sips`,
   Windows/Linux da ImageMagick `magick`, kerak boʻlsa ffmpeg). Mos
   JPG/PNG/BMP fayllariga tegmaydi.
6. Natijani `Video/`, `Music/`, `Photo/` papkalariga joylaydi.
7. Kerak boʻlsa videoni **4 GiB dan kichik qismlarga** boʻladi (FAT32 chegi).
   exFAT da boʻlish avtomatik oʻchadi.
8. `_m6media/manifest.json`, `manifest.csv`, `run.log` hisobotlarini yozadi
   va tayyor papkani `--check-only` bilan tekshira oladi.

Manba fayllar **oʻzgartirilmaydi va oʻchirilmaydi**. Skript faqat oʻqiydi
va natijani koʻrsatilgan papkaga yozadi.

Standart holatda chiqish papkasiga **faqat oʻgirish kerak boʻlgan fayllar**
tushadi. Mos fayllar oʻz joyida qoladi. Hammasini bitta formatga keltirish
uchun `--normalize` qoʻshing.

---

## Nega Haval M6 AVI/XviD oʻynamaydi

Haqiqiy oqimlardan misol (fayl nomlari umumlashtirilgan):

| Fayl | Konteyner | Video | Ovoz | Natija |
|---|---|---|---|---|
| `movie-xvid-1.avi` | AVI | MPEG-4 ASP (XviD), 704×384, 23,976 | AC3 5.1 | koʻrinmadi |
| `movie-xvid-2.avi` | AVI | MPEG-4 ASP (XviD), 720×400, 23,976 | AC3 5.1 | koʻrinmadi |
| `movie-xvid-3.avi` | AVI | MPEG-4 ASP (XviD), 720×384, 24 | AC3 5.1 | koʻrinmadi |
| `movie-xvid-4.avi` | AVI | MPEG-4 ASP (XviD), 704×352, 24 | AC3 5.1 | koʻrinmadi |
| `movie-h264-1.mkv` | MKV | H.264 High@4.1, 1104×462, 24 | AC3 5.1 | oʻynadi |
| `movie-h264-2.mkv` | MKV | H.264 High@4.1, 1152×480, 24 | AC3 5.1 | oʻynadi |
| `movie-h264-3.mkv` | MKV | H.264 High@4.1, 1152×480, 23,976 | AC3 5.1 | oʻynadi |

**Xulosa:** oʻynamaydigan fayllarning umumiy belgisi — **AVI + MPEG-4 Part 2
(XviD/DivX)**, ishlaydiganlari — **MKV + H.264**. Qoʻllanmada AVI konteyneri
bor, lekin XviD/DivX kodeki yoʻq. H.264 (MP4/MKV) ikkala farqni ham yoʻq
qiladi. Fayl nomi, hajmi, kirillitsa va exFAT — sabab emas. AC3 5.1 MKV da
M6 da oʻynaydi, lekin MP4 uchun AAC ishonchliroq.

Skript bu fayllar bilan nima qiladi:

* XviD/AVI → videoni H.264 Main@4.0 ga, ovozni AC3 dan AAC ga oʻgiradi;
* H.264/MKV + AC3 → videoni sifat yoʻqotmasdan koʻchiradi, konteynerni
  MP4 ga, ovozni AC3 dan AAC ga almashtiradi;
* oʻlchamni kattalashtirmaydi: 704×384 shundayligicha qoladi.

### Hisobotda `copy-video` nima?

`--normalize` bilan skript mos fayllarni ham ishlaydi. H.264/MKV+AC3 uchun
bu videoni qayta kodlash emas, `copy-video`:

* H.264 video bit-bit koʻchiriladi (`-c:v copy`) — sifat oʻzgarmaydi;
* AC3 5.1 → AAC stereo;
* MKV → MP4.

Logda `-c:v copy` qatori koʻrinadi. Standart holatda bunday fayllar
**oʻtkazib yuboriladi**: skript faqat videoni qayta kodlash kerak boʻlgan
joyda ishlaydi (XviD/DivX, H.264 profildan tashqari, HDR va hokazo).

```bash
./m6media.py /Volumes/USB
```

---

## Oʻrnatish

Skript shu papkada. macOS/Linux da bajariladigan qilib qoʻying:

```bash
chmod +x m6media.py
```

Windows da `chmod` kerak emas — `py -3 m6media.py` yoki
`python m6media.py` orqali ishga tushiring.

Python 3.9+ va `libx264`, `aac`, `libmp3lame` bilan ffmpeg kerak.

### macOS

```bash
brew install ffmpeg
# kerak boʻlsa, HEIC/RAW uchun:
brew install imagemagick
```

Tekshirish:

```bash
ffmpeg -version
python3 --version
```

`--burn-subs` (subtitrlarni kuydirish) va `--tonemap` (HDR→SDR) uchun
`libass`/`zscale` bor ffmpeg kerak. Oddiy Homebrew ffmpeg da ular yoʻq;
`ffmpeg-full` oʻrnatib, yoʻlini koʻrsatish mumkin:

```bash
brew install ffmpeg-full
./m6media.py … --ffmpeg /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg \
                 --ffprobe /opt/homebrew/opt/ffmpeg-full/bin/ffprobe
```

### Linux

```bash
sudo apt install ffmpeg       # Debian/Ubuntu
sudo dnf install ffmpeg       # Fedora
# kerak boʻlsa, HEIC/RAW uchun:
sudo apt install imagemagick
```

### Windows

```powershell
winget install Gyan.FFmpeg
# kerak boʻlsa, HEIC/RAW uchun:
winget install ImageMagick.ImageMagick
```

Skript `ffmpeg` ni `PATH`, `/opt/homebrew/bin`, `/usr/local/bin`,
`C:\ffmpeg\bin`, `C:\Program Files\ffmpeg\bin`, Chocolatey/WinGet ichidan
qidiradi. Aniq yoʻlni `--ffmpeg PATH`, `--ffprobe PATH` bilan berish mumkin.

---

## Tez boshlash

### 1. Fleshkani diagnostika qilish (hech narsa yozmaydi)

macOS/Linux:

```bash
python3 m6media.py /Volumes/USB --diagnose
# Linux: python3 m6media.py /media/$USER/USB --diagnose
```

Windows (PowerShell, fleshka `E:`):

```powershell
py -3 m6media.py E:\ --diagnose
```

Windows da yoʻl — disk harfi (`E:\`), chiqish — `E:\M6`.

Skript har bir fayl boʻyicha konteyner, kodeklar, oʻlcham, ovoz, amal va
sababni koʻrsatadi. Bu fayl nima uchun koʻrinmasligini tushunishning eng
oson yoʻli.

### 2. Faqat muammoli fayllarni tayyorlash

```bash
python3 m6media.py /Volumes/USB
```

Windows:

```powershell
py -3 m6media.py E:\
```

Linux:

```bash
python3 m6media.py /media/$USER/USB
```

`M6` papkasi manbalar yonida avtomatik yaratiladi. Standart holatda skript:

* **mos fayllarni oʻtkazib yuboradi** — MKV/H.264, MP3/FLAC/WAV,
  JPG/PNG/BMP;
* **xizmat fayllarini oʻtkazib yuboradi** — `.srt`, `._*`, film yonidagi
  tashqi `.ac3`;
* **faqat mos boʻlmagan fayllarni ishlaydi** — masalan, AVI/XviD;
* exFAT ni oʻzi aniqlaydi va fayllarni 4 GiB boʻyicha boʻlmaydi.

`M6` ichida faqat tuzatilgan mos boʻlmagan fayllar boʻladi. Mos MKV
fayllari oʻz joyida qoladi va takrorlanmaydi.

Qoʻshimcha imkoniyatlar:

```bash
# tezroq (480p uchun sifat farqi sezilmaydi)
... --x264-preset veryfast

# natijani darhol tekshirish
... --check

# hammasini bitta formatga keltirish
... --normalize
```

### 3. Tayyor natijani tekshirish

```bash
python3 m6media.py /Volumes/USB/M6 --check-only
# Windows: py -3 m6media.py E:\M6 --check-only
```

### 4. Lokal tayyorlash (keyin fleshkaga koʻchirish)

```bash
python3 m6media.py ~/Movies -o ~/m6-ready --preset compat
```

Agar maqsadli fleshka exFAT boʻlsa, lokal tayyorlashda:

```bash
python3 m6media.py ~/Movies -o ~/m6-ready --fat32 off
```

---

## Qayta ishga tushirish va `--force`

Agar `M6` ichida aynan shu nomdagi fayl boʻlsa, skript uni **tegmaydi**:
«файл уже существует…» deb yozadi va davom etadi. Qayta yozish uchun:

```bash
./m6media.py /Volumes/USB --force
```

`--force` faqat skript ishlaydigan fayllarni qayta yozadi. Mos fayllar
baribir oʻtkazib yuboriladi; ularni ham qayta yozish uchun
`--normalize --force`.

---

## Misollar

### Faqat mos boʻlmagan fayllar

```bash
python3 m6media.py /Volumes/USB --only video
```

Qoʻlda roʻyxat berish:

```bash
python3 m6media.py "/Volumes/USB/Movie 1.avi" "/Volumes/USB/Movie 2.avi"
```

### Hammasini qayta kodlash

```bash
python3 m6media.py ~/Movies -o ~/m6-ready --mode encode --preset quality
```

### Asl nomlarni saqlash (kirillitsa, boʻsh joy)

```bash
python3 m6media.py ~/Movies -o ~/m6-ready --keep-names
```

Standart holatda nomlar ASCII ga transliteratsiya qilinadi, **raqamsiz**:
`Pinokkio_Gilermo_del_Toro_2022.mp4`. Barqaror tartib kerak boʻlsa,
`--number` qoʻshib, `001_Pinokkio...mp4` oling. M6 kirillitsani koʻrsatadi,
shuning uchun `--keep-names` ham ishlaydi.

### Faqat musiqa / faqat rasm

```bash
python3 m6media.py ~/Music -o ~/m6-ready --only audio
python3 m6media.py ~/Photos -o ~/m6-ready --only image
```

Mos MP3/WMA/AAC/FLAC/WAV/OGG va JPG/PNG/BMP standart holatda tegmaydi.
MP3 ga qayta kodlash yoki rasmni kichraytirish uchun `--normalize` qoʻshing.

### Fayl mosmi — tez tekshirish

```bash
python3 m6media.py file.mkv --dry-run
```

---

## Asosiy parametrlar

| Parametr | Standart | Maʼnosi |
|---|---|---|
| `-o, --output` | manba yonidagi `M6` | natija papkasi |
| `--preset` | `compat` | `compat` / `quality` / `compact` |
| `--mode` | `auto` | `auto` — faqat mos emas; `copy` — qayta kodlamay; `encode` — hammasini qayta |
| `--container` | `mp4` | `mp4` yoki `mkv` |
| `--only` | `all` | `video` / `audio` / `image` |
| `--normalize` | — | mos fayllarni ham ishlash |
| `--fat32` | `auto` | `fit` — 4 GiB ga sigʻdirish; `split` — boʻlish; `off` — cheklamaslik |
| `--max-file-size` | `3.8G` | fayl chegarasi (FAT32 uchun 4 GiB dan kam) |
| `--max-width/--max-height` | 1920/1080 | kadrning eng katta oʻlchami |
| `--fps` | 30 | eng koʻp kadr/s; `0` — cheklamaslik |
| `--video-crf` | 21 | x264 sifati (kamroq — yaxshiroq) |
| `--x264-preset` | `medium` | `veryfast` tezroq, `slow` sifatliroq |
| `--video-maxrate` | 8M | video bitrate chegarasi |
| `--audio-format` | `mp3` | `mp3` / `aac` / `copy` |
| `--audio-bitrate` | 256k | musiqa bitrate |
| `--photo-max` | 1920 | rasmning uzun tomoni; `0` — kichraytirmaslik |
| `--photo-quality` | 90 | JPEG sifati |
| `--jobs` | avto (8 yadroda 2) | parallel vazifalar; USB uchun 1–2 yaxshi |
| `--threads` | avto | bitta vazifaga x264 oqimlari (yadro / jobs) |
| `--dry-run` | — | rejani koʻrsatish, yozmaslik |
| `--diagnose` | — | toʻliq diagnostika (= dry-run + verbose) |
| `--force` | — | tayyor fayllarni qayta yozish |
| `--keep-names` | — | nomlarni transliteratsiya qilmaslik |
| `--number` | — | `001_`, `002_` raqamlarini qoʻshish |
| `--check` | — | ishlovdan keyin tekshirish |
| `--check-only` | — | faqat tayyor papkani tekshirish |
| `--burn-subs` | — | tashqi `.srt/.ass` kuydirish (libass kerak) |
| `--tonemap` | — | HDR→SDR (zscale kerak) |
| `--usb` | — | USB ga chiqarish; FS va joyni tekshirish |
| `--exclude` | — | maska boʻyicha oʻtkazib yuborish |
| `--verbose` | — | toʻliq log va progress |

Profillar:

| Profil | Oʻlcham | CRF | Video chegarasi | Ovoz |
|---|---|---|---|---|
| `compat` | 1920×1080 | 21 | 8 Mbit/s | AAC 192k |
| `quality` | 1920×1080 | 19 | 12 Mbit/s | AAC 256k |
| `compact` | 1280×720 | 23 | 3 Mbit/s | AAC 128k |

---

## FAT32 uchun boʻlish

FAT32 4 GiB dan katta faylni qabul qilmaydi. Skript davomiylik va bitrateni
hisoblab, variant tanlaydi:

* `fit` (FAT uchun standart) — bitta film `--max-file-size` ichiga sigʻishi
  uchun bitrateni tushiradi. Agar chegara juda past boʻlsa (1080p uchun
  2,2 Mbit/s, 720p uchun 1,2 Mbit/s), boʻlish yoqiladi;
* `split` — sifatni saqlab, teng qismlarga boʻladi
  (`..._part01.mp4`, `..._part02.mp4`);
* `off` — cheklamaslik (exFAT/NTFS/lokal disk).

Kodlashdan keyin skript haqiqiy hajmni qayta tekshiradi. Fayl hali katta
boʻlsa, qismlar sonini koʻpaytirib qayta kodlaydi.

exFAT fleshkada boʻlish kerak emas: fayllar 4 GiB dan katta boʻlishi mumkin.

---

## Natija tuzilishi

```text
M6/
├── Video/
│   ├── movie-xvid-1.mp4
│   └── ...
├── Music/                 # faqat konvertatsiya boʻlsa
├── Photo/                 # faqat konvertatsiya boʻlsa
└── _m6media/
    ├── manifest.json      # toʻliq hisobot: manba, oqimlar, amallar
    ├── manifest.csv       # Excel uchun
    └── run.log            # jurnal
```

Bu yerda faqat haqiqatan konvertatsiya qilingan fayllar bor. Mos fayllar
oʻz joyida qoladi — chiqish papkasiga koʻchirilmaydi. `--normalize` bilan
toʻliq toʻplam boʻladi.

`_m6media` papkasini fleshkani mashinaga qoʻyishdan oldin oʻchirish mumkin,
lekin hisobot tahlil uchun foydali.

---

## Nega H.264 Main@4.0 va AAC

* **H.264** — M6 H.264 High@4.1 (MKV) ni oʻynaydi. Main@4.0 — soddaroq va
  keng tarqalgan profil.
* **AAC-LC** — qoʻllanmada bor; AC3/DTS MP4 da yomon qoʻllab-quvvatlanadi,
  shuning uchun ovoz har doim AAC ga keltiriladi.
* **8 bit 4:2:0** — HDR/10-bit va 4:2:2/4:4:4 avtomobil pleyerlarida koʻp
  hollarda oʻynalmaydi.
* **MP4 + faststart** — `moov` fayl boshida, pleyer tezroq boshlaydi.
* **Subtitrlar standart holatda yoʻq** — ichki subtitrlar olib tashlanadi.
  Kerak boʻlsa `--burn-subs` (libass kerak).

---

## Tezlik: nega uzoq va qanday tezlashtirish mumkin

Bir nechta filmni qayta kodlash — bu koʻchirish emas, soatlab davom etadigan
ish. 8 yadroli Mac da 4 vazifani birga ishga tushirib, natijani oʻsha USB
fleshkaga yozsangiz:

* 4 x264 jarayoni CPU uchun raqobatlashadi (eski versiyada har biri ~12
  oqim olib, load average ~48 ga yetardi);
* 4 fayl bir vaqtda fleshkadan oʻqilib, oʻsha fleshkaga yoziladi — USB tor
  joy boʻladi;
* har bir fayl oxirida `+faststart` butun MP4 ni qayta yozadi — USB da bu
  daqiqalar qoʻshadi.

Yangi versiyada standart holatda 2 vazifa, x264 esa `yadro / jobs`
oqimidan oshmaydi. USB uchun yana tezroq:

```bash
./m6media.py /Volumes/USB --jobs 2 --x264-preset veryfast
```

Eng yuqori tezlik uchun natijani lokal diskka yozib, keyin fleshkaga
koʻchiring:

```bash
./m6media.py /Volumes/USB -o ~/M6 --jobs 2 --x264-preset veryfast
```

Shunda fleshkadan faqat oʻqish boʻladi, yozish esa tez SSD ga tushadi.

---

## Fleshka boʻyicha maslahatlar

* Papkalarni 2–3 darajadan chuqurlashtirmang: `M6/Video`, `M6/Music`,
  `M6/Photo`.
* Oʻynatish paytida fleshkani sugʻurib olmang — M6 qoʻllanmasi qurilma
  keyin fleshkani tanimasligi mumkinligini aytadi.
* macOS da FAT/exFAT ga koʻchirgandan keyin `._имя` xizmat fayllari paydo
  boʻladi. Ular zararsiz, lekin quyidagi buyruq bilan tozalash mumkin:

  ```bash
  dot_clean -m /Volumes/USB
  ```

  (yoki `find /Volumes/USB -name '._*' -delete`). Windows/Linux da bu
  fayllar odatda paydo boʻlmaydi.
* Chiqarishdan oldin Finder da «Chiqarish» / `diskutil eject` ishlating.
* Agar M6 fleshkani umuman koʻrmasa: FAT32/exFAT, MBR boʻlinishini va
  qurilma hajmini tekshiring. Skript fleshkani formatlamaydi.

---

## Cheklovlar

* DRM bilan himoyalangan fayllar (Apple Video, Amazon va hokazo)
  qoʻllab-quvvatlanmaydi.
* Buzilgan/toʻliq yuklanmagan fayl oʻqilmasligi mumkin — skript xatoni
  koʻrsatib, qolganlarini davom ettiradi.
* Birinchi audio yoʻl va birinchi video olinadi; qolganlari tashlanadi.
  Tashqi `.ac3` qoʻshilmaydi.
* Boʻlimlar oʻchiriladi (`-map_chapters -1`).
* Subtitrlar: ichkilar oʻchiriladi; tashqilarni faqat libass bor ffmpeg
  bilan kuydirish mumkin.
* HDR→SDR `--tonemap`/zscale boʻlmasa, ranglar xira koʻrinishi mumkin.
* Standart holatda mos fayllar chiqish papkasiga **koʻchirilmaydi** — ular
  oʻz joyida qoladi. Bu xato emas; toʻliq nusxa uchun `--normalize`.
* Skript fleshkani formatlamaydi. M6 koʻrmasa, FAT32 (yoki ishlayotgan
  exFAT) qilib formatlab, xavfsiz chiqaring.

---

## Tekshirish va hisobotlar

```bash
# ishlovdan keyin
python3 m6media.py ~/Movies -o ~/m6-ready --check

# tayyor papkani alohida tekshirish
python3 m6media.py ~/m6-ready --check-only

# nima qilinganini koʻrish
python3 -m json.tool ~/m6-ready/_m6media/manifest.json | less
```

`--check` har bir chiqish faylini qayta oʻqib tekshiradi:

* MP4 konteyneri;
* H.264, profil/level, `yuv420p`, oʻlcham, fps;
* AAC-LC, ≤ 2 kanal;
* fayl chegarasi;
* davomiylik (boʻlinmagan fayllar uchun);
* JPEG va rasm oʻlchami.

---

## Testlar

```bash
make check    # py_compile + 39 unit-test, ffmpeg kerak emas
make test     # faqat unit-testlar
make smoke    # 2 soniyalik sintetik kliplar bilan end-to-end, ffmpeg kerak
# Windows: py -3 tests/smoke_test.py
```

Testlar ffmpeg siz ham ishlaydi: transliteratsiya, nomlar, parametrlar,
moslik va boʻlish rejasi tekshiriladi.

---

## AI agentlar uchun

Repozitoriy kodlash agentlariga moslashtirilgan:

* [AGENTS.md](AGENTS.md) — kanonik koʻrsatmalar, invariantlar va xavfsizlik;
* [llms.txt](llms.txt) — qisqa mashina indeksi;
* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — pipeline, maʼlumotlar modeli,
  amallar va qaytarish kodlari;
* [FAQ.uz.md](FAQ.uz.md) va [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) —
  savollar va moslik jadvali;
* [README.en.md](README.en.md), [README.kk.md](README.kk.md);
* [schema/manifest.schema.json](schema/manifest.schema.json) — hisobot sxemasi;
* [docs/SEO.md](docs/SEO.md) — GitHub metamaʼlumotlari va qidiruv strategiyasi.

Qoida: haqiqiy film nomlari, reliz nomlari, shaxsiy yoʻllar, sirlar va media
fayllarni qoʻshmaslik. Testlar uchun faqat sintetik `lavfi` kliplari va
`movie-xvid-1.avi` kabi umumiy nomlar ishlatiladi.

---

## Litsenziya

Loyiha [MIT License](LICENSE) boʻyicha tarqatiladi.
Copyright (c) 2026 m6media contributors.

## Minnatdorchilik

Formatlar Haval M6 Plus (2023–2026) foydalanuvchi qoʻllanmasining 116-betiga
solingan ([manba](https://mcgrp.ru/files/viewer/1112377/117)).
ffmpeg, x264, LAME va Homebrew loyihalariga rahmat.
