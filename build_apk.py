"""
Build an Android APK from converted WebP stickers, using WhatsApp's official
sample sticker app (github.com/WhatsApp/stickers) as the base.

Generates assets/contents.json + assets/<id>/ folders, then runs Gradle.

Env vars:
  PACK_NAME   Display name for the sticker pack  (default: "My Sticker Pack")
  PUBLISHER   Publisher name                      (default: "Sticker Converter")
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

INPUT_DIR    = Path("/input")
OUTPUT_DIR   = Path("/output")
PROJECT_DIR  = Path("/build/android-app")
ASSETS_DIR   = PROJECT_DIR / "app/src/main/assets"
COUNTER_FILE = OUTPUT_DIR / "pack_counter.txt"

PACK_NAME    = os.environ.get("PACK_NAME", "My Sticker Pack")
PUBLISHER    = os.environ.get("PUBLISHER", "Sticker Converter")
MAX_PER_PACK = 30


def read_counter() -> int:
    if COUNTER_FILE.exists():
        try:
            return int(COUNTER_FILE.read_text().strip())
        except ValueError:
            pass
    return 1


def write_counter(next_value: int):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    COUNTER_FILE.write_text(str(next_value))


def first_frame(path: Path) -> Image.Image:
    img = Image.open(str(path))
    img.seek(0)
    return img.convert("RGBA")


def make_tray_png(src: Path, dest: Path):
    """96x96 PNG tray icon (official app uses PNG trays, must be <= 50KB)."""
    first_frame(src).resize((96, 96), Image.LANCZOS).save(str(dest), "PNG", optimize=True)


def main():
    def sort_key(p):
        return int(p.stem) if p.stem.isdigit() else p.stem

    webp_files = sorted(INPUT_DIR.glob("*.webp"), key=sort_key)
    if not webp_files:
        print(f"No .webp files found in {INPUT_DIR}")
        sys.exit(1)

    print(f"Found {len(webp_files)} WebP files")

    # Clean any previous assets, keep the folder
    if ASSETS_DIR.exists():
        shutil.rmtree(ASSETS_DIR)
    ASSETS_DIR.mkdir(parents=True)

    start_counter = read_counter()
    print(f"Pack counter starts at: {start_counter}")

    chunks = [webp_files[i:i + MAX_PER_PACK] for i in range(0, len(webp_files), MAX_PER_PACK)]
    sticker_packs = []

    for idx, chunk in enumerate(chunks):
        pack_num = start_counter + idx
        identifier = str(pack_num)
        pack_dir = ASSETS_DIR / identifier
        pack_dir.mkdir()

        label = f"{PACK_NAME}-pack-{pack_num}"

        stickers = []
        for f in chunk:
            shutil.copy2(f, pack_dir / f.name)
            stickers.append({"image_file": f.name, "emojis": ["😊"]})

        tray_name = "tray.png"
        make_tray_png(chunk[0], pack_dir / tray_name)

        sticker_packs.append({
            "identifier":                identifier,
            "name":                      label,
            "publisher":                 PUBLISHER,
            "tray_image_file":           tray_name,
            "image_data_version":        "1",
            "avoid_cache":               False,
            "publisher_email":           "",
            "publisher_website":         "",
            "privacy_policy_website":    "",
            "license_agreement_website": "",
            "animated_sticker_pack":     True,
            "stickers":                  stickers,
        })
        print(f"  Pack {identifier}: '{label}' — {len(stickers)} stickers")

    contents = {
        "android_play_store_link": "",
        "ios_app_store_link":      "",
        "sticker_packs":           sticker_packs,
    }
    (ASSETS_DIR / "contents.json").write_text(json.dumps(contents, indent=2))

    # local.properties (SDK path + skip the sample app's applicationId guard)
    (PROJECT_DIR / "local.properties").write_text(
        f"sdk.dir={os.environ['ANDROID_HOME']}\nignoreApplicationIdCheck=true\n"
    )

    print("\nBuilding APK (official WhatsApp sample app)…")
    result = subprocess.run(
        ["gradle", "-p", str(PROJECT_DIR), "assembleDebug", "--no-daemon"],
        timeout=900,
    )
    if result.returncode != 0:
        print("\nBuild failed.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    apk_src = PROJECT_DIR / "app/build/outputs/apk/debug/app-debug.apk"
    apk_dst = OUTPUT_DIR / "sticker-pack.apk"
    shutil.copy2(apk_src, apk_dst)

    next_counter = start_counter + len(chunks)
    write_counter(next_counter)

    size_mb = apk_dst.stat().st_size / (1024 * 1024)
    print(f"\n✓ APK ready: output/sticker-pack.apk  ({size_mb:.1f} MB)")
    print(f"  {len(webp_files)} stickers in {len(chunks)} pack(s)  (packs {start_counter}–{next_counter - 1})")
    print(f"  Next run will start at pack {next_counter}  (saved to output/pack_counter.txt)")
    print("\nNext steps:")
    print("  1. Copy sticker-pack.apk to your Android phone")
    print("  2. Tap it to install (allow 'Install unknown apps' once)")
    print("  3. Open the app, open a pack, tap 'Add to WhatsApp'")


if __name__ == "__main__":
    main()
