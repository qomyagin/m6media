# Haval M6: mos boʻlmagan videolar va fleshkalar — FAQ

**Til:** [Русский](FAQ.md) · [Қазақша](FAQ.kk.md) · Oʻzbekcha

Qisqa javob: **Haval M6 (2023 / M6 Plus) qoʻllanmada koʻrsatilgan barcha
kodeklarni oʻqiy olmaydi.** Koʻpincha AVI/XviD (MPEG-4 Part 2), MKV dan
tashqari AC3/DTS ovozli videolar, HDR/10-bit va H.264 ning qoʻllab-
quvvatlanmaydigan profili koʻrinmaydi. Ishonchli maqsadli format —
**MP4 + H.264 Main@4.0 + AAC-LC stereo**.

Ushbu repozitoriydagi vosita bunday fayllarni oʻzi topadi va faqat ularni
konvertatsiya qiladi. Mos fayllarga tegmaydi.

## Haval M6 fleshkadagi filmni koʻrmayapti — nima qilish kerak?

1. Fleshka oʻqilishiga ishonch hosil qiling: FAT32/exFAT, NTFS emas.
2. Diagnostikani ishga tushiring — konteyner, kodeklar va sabab koʻrinadi:

   ```bash
   ./m6media.py /Volumes/USB --diagnose
   # Windows: py -3 m6media.py E:\ --diagnose
   ```

3. Agar videoda `mpeg4` / `XviD` / `DivX` boʻlsa — H.264 ga oʻgiring:

   ```bash
   ./m6media.py /Volumes/USB
   # Windows: py -3 m6media.py E:\
   ```

4. Tayyor fayllar `/Volumes/USB/M6` (Windows: `E:\M6`) ichida paydo boʻladi.

## AVI qoʻllab-quvvatlansa, nega oʻynamaydi?

Qoʻllanma **konteynerlarni** sanaydi, kodeklarni emas. AVI ichida
MPEG-4 Part 2 (XviD/DivX) boʻlishi mumkin, M6 dekoderi esa uni tushunmaydi.
Rasmiy jihatdan AVI qoʻllab-quvvatlanadi, lekin aniq fayl — yoʻq.

Toʻliq jadval: [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Haval M6 qanday formatlarni qoʻllab-quvvatlaydi?

| Tur | Formatlar |
|---|---|
| Video | WMV, MP4, MPEG, AVI, 3GP, MKV, MOV, ASF, VOB |
| Audio | MP3, WMA, AAC, FLAC, WAV, OGG |
| Rasm | JPG, PNG, BMP |
| USB | FAT16, FAT32 |

Manba: Haval M6 Plus (2023–2026) qoʻllanmasi, 116-bet,
[skan](https://mcgrp.ru/files/viewer/1112377/117).

## Nega MKV oʻynaydi, AVI oʻynamaydi?

Chunki MKV ichida odatda M6 dekodlaydigan H.264/AVC boʻladi, AVI ichida esa
eski XviD/DivX. Konteyner ikkinchi darajali; hal qiluvchi — video kodeki.

## Video bor, ovoz yoʻq

Koʻpincha ovoz AC3, E-AC3 yoki DTS, pleyer esa AAC/MP3 kutadi. MKV dagi AC3
M6 da koʻp hollarda oʻynaydi, MP4 da esa — yoʻq. Skript ovozni AAC-LC
stereo ga keltiradi, videoni imkon qadar sifat yoʻqotmasdan koʻchiradi.

## exFAT yoki FAT32?

Qoʻllanma FAT16/FAT32 vaʼda qiladi. Amalda exFAT M6 da koʻp hollarda
ishlaydi; skript buni hisobga oladi va exFAT da fayllarni 4 GiB boʻyicha
boʻlmaydi. Agar fleshka koʻrinmasa — FAT32 ni sinab koʻring.

## 4 GB dan katta fayl fleshkaga koʻchmayapti

Bu FAT32 chegarasi. Variantlar:

* exFAT (agar M6 oʻqisa);
* `--fat32 split` — filmni qismlarga boʻlish;
* `--preset compact` — bitrateni kamaytirish.

## Faqat muammoli fayllarni qanday konvertatsiya qilish kerak?

Standart holatda aynan shunday:

```bash
./m6media.py /Volumes/USB
```

Mos fayllar oʻtkazib yuboriladi, mavjud fayllar qayta yozilmaydi, sababi
oxirida chop etiladi. Qayta yozish uchun — `--force`.

## Nega ishlayotgan MKV ni konvertatsiya qilmaslik kerak?

Agar fayl allaqachon oʻynasa, ortiqcha konvertatsiya faqat vaqt oladi va
rasm sifatini yomonlashtirishi mumkin. Skript standart holatda mos faylni
shundayligicha qoldiradi. `--normalize` butun kutubxonani bitta formatga
keltirish uchun kerak.

## Fayl menyuda bor, lekin qora ekran

Koʻpincha bu H.264 High@4.1+ 1080p, 10-bit/HDR, 4:2:2 yoki juda yuqori
bitrate. Skriptning maqsadli profili — Main@4.0, yuv420p, 8 bit,
1080p va 30 fps gacha.

## Tayyor faylni qanday tekshirish kerak?

```bash
./m6media.py /Volumes/USB/M6 --check-only
# Windows: py -3 m6media.py E:\M6 --check-only
```

Yoki qoʻlda:

```bash
ffprobe -v error -show_streams -show_format file.mp4
```

## English

**Haval M6 does not play AVI/XviD files?** The container may be supported
while the MPEG-4 Part 2 codec is not. Convert video to H.264 Main@4.0 +
AAC-LC in MP4. See [README.en.md](README.en.md) and
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Yana qarang

* [README.uz.md](README.uz.md) — toʻliq qoʻllanma.
* [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) — kodeklar va belgilar
  jadvali.
* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — skript qanday ishlaydi.
* [llms.txt](llms.txt) — AI qidiruvi uchun qisqa indeks.
