#!/usr/bin/env bash
# Full pipeline: extract zips → deduplicate → convert → build APK

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STICKERS_DIR="$SCRIPT_DIR/stickers"
MERGED_DIR="$SCRIPT_DIR/stickers-merged"
WEBP_DIR="$SCRIPT_DIR/stickers-webp"
OUTPUT_DIR="$SCRIPT_DIR/output"

cd "$SCRIPT_DIR"

echo "=== Step 1: Prepare merged input folder ==="
# Only re-extract if merged dir is missing or empty
if [[ -d "$MERGED_DIR" && $(find "$MERGED_DIR" -type f | wc -l) -gt 0 ]]; then
    echo "  Merged dir already populated ($(find "$MERGED_DIR" -type f | wc -l | tr -d ' ') files), skipping extraction."
    echo "  Delete stickers-merged/ manually to force re-extraction."
else
    rm -rf "$MERGED_DIR"
    mkdir -p "$MERGED_DIR"
fi

# Extract a zip into MERGED_DIR, renaming files to {prefix}_{num:04d}.{ext}
# Only extracts .tgs and .webm files.
# If skip_if_tgs=1, skips .webm files where a .tgs with the same stem already exists.
extract_zip() {
    local zipfile="$1"
    local prefix="$2"
    local skip_if_tgs="${3:-0}"

    echo "  Extracting $(basename "$zipfile") as prefix='$prefix'..."
    local tmpdir
    tmpdir=$(mktemp -d)
    unzip -q "$zipfile" -d "$tmpdir" 2>/dev/null || true

    # Write matching file list to a temp file (avoids pipe subshell issue)
    local filelist
    filelist=$(mktemp)
    find "$tmpdir" -type f \( -name "*.tgs" -o -name "*.webm" \) > "$filelist"

    local copied=0 skipped=0
    while IFS= read -r src; do
        local basename ext stem dest_stem dst
        basename="$(basename "$src")"
        ext="${basename##*.}"
        stem="${basename%.*}"
        # zero-pad numeric stems for consistent sort order
        if [[ "$stem" =~ ^[0-9]+$ ]]; then
            stem=$(printf "%04d" "$stem")
        fi
        dest_stem="${prefix}_${stem}"
        dst="$MERGED_DIR/${dest_stem}.${ext}"

        if [[ "$skip_if_tgs" == "1" && -f "$MERGED_DIR/${dest_stem}.tgs" ]]; then
            skipped=$((skipped + 1))
            continue
        fi

        cp "$src" "$dst"
        copied=$((copied + 1))
    done < "$filelist"

    rm -f "$filelist"
    rm -rf "$tmpdir"
    echo "    copied: $copied  skipped (TGS exists): $skipped"
}

# TGS-only packs
extract_zip "$STICKERS_DIR/HANGSEED_Mochi_batch_tgs.zip"                        "a_hangseed_mochi"
extract_zip "$STICKERS_DIR/animation_1_1_Cat2_batch_tgs.zip"                    "b_cat2"

# Packs with both TGS + WebM — TGS first, then WebM only for non-overlapping stickers
extract_zip "$STICKERS_DIR/HANGSEED9_batch_tgs.zip"                             "c_hangseed9"
extract_zip "$STICKERS_DIR/HANGSEED9_batch_webm.zip"                            "c_hangseed9" "1"

extract_zip "$STICKERS_DIR/Inocentyyyyyyyyyyyyyyy_by_fStikBot_batch_tgs.zip"    "d_inocentyyy"
extract_zip "$STICKERS_DIR/Inocentyyyyyyyyyyyyyyy_by_fStikBot_batch_webm.zip"   "d_inocentyyy" "1"

# WebM-only packs
extract_zip "$STICKERS_DIR/monkey_cat_luna_batch_webm.zip"                      "e_monkey_cat"
extract_zip "$STICKERS_DIR/sticker_af2ffbeb_by_moe_sticker_bot_batch_webm.zip" "f_moe_bot"
extract_zip "$STICKERS_DIR/Webp_24_batch_webm.zip"                              "g_webp24"

total=$(find "$MERGED_DIR" -type f \( -name "*.tgs" -o -name "*.webm" \) | wc -l | tr -d ' ')
echo "  Total unique stickers to convert: $total"

echo ""
echo "=== Step 2: Build converter image ==="
docker build -t sticker-converter . -q
echo "  Done"

echo ""
echo "=== Step 3: Convert all stickers to WebP ==="
mkdir -p "$WEBP_DIR"
docker run --rm \
    -v "$MERGED_DIR:/input:ro" \
    -v "$WEBP_DIR:/output" \
    sticker-converter

webp_count=$(find "$WEBP_DIR" -name "*.webp" | wc -l | tr -d ' ')
echo ""
echo "  Converted: $webp_count WebP files"

echo ""
echo "=== Step 4: Build APK image ==="
docker build -f Dockerfile.apk -t sticker-apk-builder . -q
echo "  Done"

echo ""
echo "=== Step 5: Build APK ==="
mkdir -p "$OUTPUT_DIR"
docker run --rm \
    -e PACK_NAME="vr_ayush" \
    -e PUBLISHER="vr_ayush" \
    -v "$WEBP_DIR:/input:ro" \
    -v "$OUTPUT_DIR:/output" \
    sticker-apk-builder

echo ""
echo "=== Done ==="
echo "APK: $OUTPUT_DIR/sticker-pack.apk"
