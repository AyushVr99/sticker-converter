# Sticker Converter — Usage Guide

Convert Telegram sticker packs (`.tgs`, `.webm`, `.gif`, or `.zip`) into a WhatsApp sticker APK — bulk, Docker-only, no dependencies on the host.

## Prerequisites

- Docker installed and running
- An Android phone

---

## One-time setup

```bash
# Converter image: TGS/WebM/GIF → WebP
docker build -t sticker-converter .

# APK builder image: WebP → Android APK  (~5 min first time, downloads Gradle + Android SDK)
docker build -f Dockerfile.apk -t sticker-apk-builder .
```

---

## Adding a new batch of stickers

### Step 1 — Drop your sticker files into `stickers/`

Supported inputs (mix freely):
- `.tgs` — Telegram animated stickers (Lottie)
- `.webm` — Telegram video stickers
- `.gif` — animated GIFs
- `.zip` — zip of any of the above (auto-extracted)

```
stickers/
  my_pack_batch_tgs.zip
  my_pack_batch_webm.zip
  some_other.tgs
  ...
```

### Step 2 — Run the full pipeline

```bash
bash build_all.sh
```

This script does everything in one shot:
1. Extracts all zips into `stickers-merged/` (skips if already done)
2. Deduplicates — if the same sticker exists as both `.tgs` and `.webm`, keeps `.tgs` (better quality)
3. Converts all stickers to WebP into `stickers-webp/` (skips already-converted files on re-run)
4. Removes any stickers over 500 KB (WhatsApp rejects them)
5. Builds `output/sticker-pack.apk`

Pack names are auto-numbered: `vr_ayush-pack-1`, `vr_ayush-pack-2`, … up to 30 stickers per pack.
The counter is saved to `output/pack_counter.txt` — the next run continues from where this one left off (e.g. `vr_ayush-pack-21`, `vr_ayush-pack-22`, …).

### Step 3 — Install the APK on your phone

1. Copy `output/sticker-pack.apk` to your Android phone (USB, Google Drive, AirDrop via WhatsApp, etc.)
2. Tap the APK → install (allow "Install unknown apps" once if prompted)
3. Open the app, open a pack, tap **"Add to WhatsApp"**
4. Repeat for each pack

---

## Re-running / resuming after a crash

The pipeline is resumable. If Docker crashes mid-conversion:

1. Delete any corrupt files (files over 500 KB that weren't supposed to be):
   ```bash
   # Check for oversized files
   find stickers-webp/ -name "*.webp" -size +500k
   # Delete them
   find stickers-webp/ -name "*.webp" -size +500k -delete
   ```
2. Re-run `bash build_all.sh` — already-converted files are skipped automatically.

To start completely from scratch:
```bash
rm -rf stickers-merged/ stickers-webp/
bash build_all.sh
```

To reset the pack counter (start numbering from 1 again):
```bash
rm output/pack_counter.txt
```

---

## Customising the pack name / publisher

Edit the relevant lines in `build_all.sh`:

```bash
docker run --rm \
    -e PACK_NAME="vr_ayush" \   # packs will be named vr_ayush-pack-1, vr_ayush-pack-2 …
    -e PUBLISHER="vr_ayush" \
    ...
```

---

## How it works

| Component | What it does |
|---|---|
| `convert.py` | Renders TGS via rlottie; decodes WebM/GIF via ffmpeg; encodes everything as animated WebP (VP8L lossless, 512×512, ≤30fps, ≤8s, <500KB) |
| `build_apk.py` | Injects WebP files + `contents.json` into WhatsApp's official sample app, then builds a debug APK with Gradle |
| `android-app/` | WhatsApp's official sticker sample app (verbatim) — required because WhatsApp's sticker preview needs Facebook Fresco's WebP renderer; a hand-rolled app will always fail |
| `build_all.sh` | Orchestrates the full pipeline end-to-end with dedup and resume support |

## WhatsApp sticker limits (enforced automatically)

| Requirement | Limit |
|---|---|
| Dimensions | 512 × 512 px |
| Frame rate | ≤ 30 fps |
| Duration | ≤ 8 s |
| File size | < 500 KB per sticker |
| Stickers per pack | 3 – 30 (auto-split) |
| Tray icon | 96 × 96 PNG, ≤ 50 KB |
