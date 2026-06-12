import os
import sys
import subprocess
import tempfile
import zipfile
from pathlib import Path
from PIL import Image

INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
TARGET_SIZE = 512
MAX_BYTES = 500 * 1024
MAX_FPS = 30
MAX_SECONDS = 8
FORMAT = os.environ.get("FORMAT", "webp").lower()  # "webp" or "gif"

SUPPORTED_EXTS = {".tgs", ".webm", ".gif"}


# ── zip extraction ────────────────────────────────────────────────────────────

def extract_zips(directory: Path):
    """Unzip any .zip files found directly in directory (flat extraction)."""
    for zf in list(directory.glob("*.zip")):
        print(f"Extracting {zf.name}...")
        with zipfile.ZipFile(zf, "r") as z:
            for member in z.namelist():
                name = Path(member).name
                if not name or Path(member).suffix.lower() not in SUPPORTED_EXTS:
                    continue
                target = directory / name
                with z.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
        print(f"  Done: extracted supported files from {zf.name}")


# ── frame rendering (TGS via rlottie) ────────────────────────────────────────

def render_frames(tgs_path: Path, step: int, size: int = TARGET_SIZE):
    from rlottie_python import LottieAnimation

    anim = LottieAnimation.from_tgs(str(tgs_path))
    total = anim.lottie_animation_get_totalframe()
    fps = anim.lottie_animation_get_framerate()

    if total == 0:
        return [], 0

    frame_ms = max(1, round(1000 / (fps / step)))
    max_frames = int(MAX_SECONDS * 1000 / frame_ms)
    indices = list(range(0, total, step))[:max_frames]

    frames = []
    for idx in indices:
        buf = anim.lottie_animation_render(frame_num=idx, width=size, height=size)
        img = Image.frombuffer("RGBA", (size, size), buf, "raw", "BGRA", 0, 1)
        frames.append(img)

    del anim
    return frames, frame_ms


# ── frame extraction (WebM / GIF via ffmpeg) ──────────────────────────────────

def extract_frames_ffmpeg(src: Path, step_fps: float, tmpdir: str):
    """Use ffmpeg to extract frames from WebM or GIF at given fps, scaled to 512x512.
    Returns (list of PNG paths, frame_ms).
    """
    frame_ms = max(1, round(1000 / step_fps))
    out_pattern = f"{tmpdir}/frame_%04d.png"
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", f"fps={step_fps},scale={TARGET_SIZE}:{TARGET_SIZE}:flags=lanczos,format=rgba",
        "-t", str(MAX_SECONDS),  # hard cap on output duration (more reliable than -vframes)
        out_pattern,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode().strip())
    paths = sorted(Path(tmpdir).glob("frame_*.png"), key=lambda p: p.name)
    return [str(p) for p in paths], frame_ms


# ── WebP output (via img2webp — reference libwebp encoder) ───────────────────

def save_webp(frame_paths: list, frame_ms: int, out_path: Path, quality: int,
              lossless: bool) -> int:
    # WhatsApp requires exactly 512x512 frames. To fit under the size limit we
    # reduce frame count and (if needed) drop from VP8L lossless to VP8 lossy —
    # never the resolution. Official stickers are lossless; we prefer it.
    cmd = ["img2webp", "-loop", "0"]
    mode = "-lossless" if lossless else "-lossy"
    for fp in frame_paths:
        cmd += [mode, "-q", str(quality), "-d", str(frame_ms), fp]
    cmd += ["-o", str(out_path)]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode().strip())
    return out_path.stat().st_size


def convert_video_webp(src: Path, out_path: Path) -> bool:
    """Convert WebM or GIF → animated WebP using ffmpeg frame extraction."""
    # Try progressively lower fps to fit under 500 KB
    fps_attempts = [
        (min(MAX_FPS, 30), True,  90),
        (min(MAX_FPS, 30), False, 80),
        (min(MAX_FPS, 30), False, 60),
        (15,               False, 60),
        (15,               False, 40),
        (10,               False, 40),
        (10,               False, 30),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        rendered = {}  # fps -> (paths, frame_ms)
        for fps, lossless, quality in fps_attempts:
            if fps not in rendered:
                try:
                    paths, frame_ms = extract_frames_ffmpeg(src, fps, tmpdir)
                except RuntimeError:
                    rendered[fps] = (None, 0)
                    continue
                rendered[fps] = (paths, frame_ms)

            paths, frame_ms = rendered[fps]
            if not paths:
                continue
            if save_webp(paths, frame_ms, out_path, quality, lossless) <= MAX_BYTES:
                return True

    return True  # best effort


def convert_webp(tgs_path: Path, out_path: Path) -> bool:
    from rlottie_python import LottieAnimation

    anim = LottieAnimation.from_tgs(str(tgs_path))
    total = anim.lottie_animation_get_totalframe()
    fps = anim.lottie_animation_get_framerate()
    del anim

    if total == 0:
        return False

    min_step = max(1, int(fps / MAX_FPS))

    # Each attempt: (frame step, lossless?, quality). Always rendered at 512x512.
    # Order: prefer lossless + full frame rate, then thin frames, then lossy.
    attempts = [
        (min_step,     True,  90),
        (min_step * 2, True,  90),
        (min_step * 3, True,  90),
        (min_step,     False, 80),
        (min_step,     False, 60),
        (min_step * 2, False, 60),
        (min_step * 2, False, 40),
        (min_step * 3, False, 40),
        (min_step * 4, False, 30),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        rendered = {}  # step -> (frame_paths, frame_ms), cached so we render once per step
        for step, lossless, quality in attempts:
            if step not in rendered:
                frames, frame_ms = render_frames(tgs_path, step, size=TARGET_SIZE)
                if not frames:
                    rendered[step] = (None, 0)
                else:
                    paths = []
                    for i, img in enumerate(frames):
                        p = f"{tmpdir}/f{step}_{i:04d}.png"
                        img.save(p, "PNG")
                        paths.append(p)
                    rendered[step] = (paths, frame_ms)

            frame_paths, frame_ms = rendered[step]
            if not frame_paths:
                continue
            if save_webp(frame_paths, frame_ms, out_path, quality, lossless) <= MAX_BYTES:
                return True

    return True  # best effort (still 512x512, just possibly over size)


# ── GIF output ───────────────────────────────────────────────────────────────

def to_palette(img: Image.Image) -> Image.Image:
    """Convert RGBA frame to palette mode preserving binary transparency."""
    return img.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)


def convert_gif(tgs_path: Path, out_path: Path) -> bool:
    from rlottie_python import LottieAnimation

    anim = LottieAnimation.from_tgs(str(tgs_path))
    total = anim.lottie_animation_get_totalframe()
    fps = anim.lottie_animation_get_framerate()
    del anim

    if total == 0:
        return False

    min_step = max(1, int(fps / MAX_FPS))
    frames, frame_ms = render_frames(tgs_path, min_step)

    gif_frames = [to_palette(f) for f in frames]
    gif_frames[0].save(
        str(out_path),
        format="GIF",
        save_all=True,
        append_images=gif_frames[1:],
        loop=0,
        duration=frame_ms,
        disposal=2,
        optimize=False,
    )
    return True


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    if FORMAT not in ("webp", "gif"):
        print(f"Unknown FORMAT={FORMAT!r}. Use 'webp' or 'gif'.")
        sys.exit(1)

    # Auto-extract any zip files in the input directory
    extract_zips(INPUT_DIR)

    def sort_key(p):
        return int(p.stem) if p.stem.isdigit() else p.stem

    src_files = sorted(
        [f for f in INPUT_DIR.iterdir() if f.suffix.lower() in SUPPORTED_EXTS],
        key=sort_key,
    )
    if not src_files:
        print(f"No supported files (.tgs, .webm, .gif) found in {INPUT_DIR}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total = len(src_files)
    print(f"Converting {total} sticker(s) to {FORMAT.upper()}...\n")

    ok = err = skipped = 0
    for i, src in enumerate(src_files, 1):
        ext = src.suffix.lower()
        dst = OUTPUT_DIR / (src.stem + f".{FORMAT}")

        # Resume: skip files that already converted successfully (<= 500KB valid output)
        if dst.exists() and 0 < dst.stat().st_size <= MAX_BYTES * 1.2:
            skipped += 1
            continue

        print(f"[{i:>3}/{total}] {src.name:<16} -> {dst.name}", end="", flush=True)
        try:
            if FORMAT == "gif":
                if ext == ".tgs":
                    success = convert_gif(src, dst)
                else:
                    # For WebM/GIF input with gif output: ffmpeg → gif via Pillow
                    with tempfile.TemporaryDirectory() as tmpdir:
                        paths, frame_ms = extract_frames_ffmpeg(src, MAX_FPS, tmpdir)
                        frames = [Image.open(p).convert("RGBA") for p in paths]
                    gif_frames = [to_palette(f) for f in frames]
                    gif_frames[0].save(
                        str(dst), format="GIF", save_all=True,
                        append_images=gif_frames[1:], loop=0,
                        duration=frame_ms, disposal=2, optimize=False,
                    )
                    success = True
            else:
                if ext == ".tgs":
                    success = convert_webp(src, dst)
                else:
                    success = convert_video_webp(src, dst)

            if success:
                kb = dst.stat().st_size // 1024
                flag = " !" if kb > 500 else ""
                print(f"  {kb} KB{flag}")
                ok += 1
        except Exception as exc:
            print(f"  ERROR: {exc}")
            err += 1

    print(f"\nDone — {ok} converted, {skipped} skipped (already done), {err} failed.")


if __name__ == "__main__":
    main()
