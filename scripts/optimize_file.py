#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2025 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
File Optimizer for PaddleOCR Document Parsing

Compresses and optimizes large files to meet size requirements.
Supports image files only.

Usage:
    python scripts/optimize_file.py input.png output.png --quality 85
"""

import argparse
import math
import os
import sys
import tempfile
from pathlib import Path

from safe_io import OutputPathError, atomic_replace, reject_collisions

MAX_TARGET_SIZE_MB = 2048


def optimize_image(
    input_path: Path,
    output_path: Path,
    quality: int = 85,
    max_size_mb: float = 20,
    *,
    force: bool = False,
) -> Path:
    """
    Optimize image file by reducing quality and/or resolution

    Args:
        input_path: Input image path
        output_path: Output image path
        quality: JPEG quality (1-100, lower = smaller file)
        max_size_mb: Target max size in MB
    """
    try:
        from PIL import Image
    except ImportError:
        print("ERROR: Pillow not installed")
        print("Install with: pip install Pillow")
        sys.exit(1)

    if not 1 <= quality <= 100:
        raise ValueError("quality must be between 1 and 100")
    if (
        not math.isfinite(max_size_mb)
        or not 0 < max_size_mb <= MAX_TARGET_SIZE_MB
    ):
        raise ValueError(
            f"target size must be between 0 and {MAX_TARGET_SIZE_MB} MB"
        )

    input_path = input_path.expanduser()
    if input_path.is_symlink() and os.getenv("PADDLEOCR_ALLOW_SYMLINKS", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise ValueError("Symbolic-link image inputs are disabled by default")
    if not input_path.is_file():
        raise ValueError(f"Input image is not a regular file: {input_path}")

    print(f"Optimizing image: {input_path}")

    output_path = reject_collisions(
        output_path,
        [input_path],
        force=force,
        label="image output",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", suffix=".tmp", dir=str(output_path.parent)
    )
    os.close(temp_fd)
    temp_path = Path(temp_name)

    try:
        source_img = Image.open(input_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    img = source_img
    if getattr(source_img, "is_animated", False) or getattr(source_img, "n_frames", 1) > 1:
        source_img.close()
        temp_path.unlink(missing_ok=True)
        raise ValueError("Multi-frame images are not supported by optimize_file.py")
    original_size = input_path.stat().st_size / 1024 / 1024

    print(f"Original size: {original_size:.2f}MB")
    print(f"Original dimensions: {img.size[0]}x{img.size[1]}")

    # Determine output format
    output_format = output_path.suffix.lower()
    if output_format in [".jpg", ".jpeg"]:
        save_format = "JPEG"
    elif output_format == ".png":
        save_format = "PNG"
    elif output_format in [".tif", ".tiff"]:
        save_format = "TIFF"
    elif output_format == ".bmp":
        save_format = "BMP"
    else:
        img.close()
        temp_path.unlink(missing_ok=True)
        raise ValueError(f"Unsupported output image format: {output_path.suffix}")

    # JPEG cannot store alpha or palette transparency; other formats keep the source mode.
    if save_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        converted = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        converted.paste(rgba, mask=rgba.getchannel("A"))
        rgba.close()
        img = converted

    # Try saving with specified quality
    try:
        img.save(temp_path, format=save_format, quality=quality, optimize=True)
        new_size = temp_path.stat().st_size / 1024 / 1024

        # If still too large, reduce resolution.
        for step in range(1, 8):
            if new_size <= max_size_mb:
                break
            scale_factor = 1.0 - step * 0.1
            new_width = max(1, int(img.size[0] * scale_factor))
            new_height = max(1, int(img.size[1] * scale_factor))

            print(f"Resizing to {new_width}x{new_height} (scale: {scale_factor:.2f})")

            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            try:
                resized.save(temp_path, format=save_format, quality=quality, optimize=True)
                new_size = temp_path.stat().st_size / 1024 / 1024
            finally:
                resized.close()

        print(f"Optimized size: {new_size:.2f}MB")
        print(f"Reduction: {((original_size - new_size) / original_size * 100):.1f}%")

        if new_size > max_size_mb:
            raise RuntimeError(
                f"Optimized file is still larger than target {max_size_mb}MB: {new_size:.2f}MB"
            )
        with temp_path.open("rb") as prepared:
            os.fsync(prepared.fileno())
        return atomic_replace(temp_path, output_path, force=force)
    finally:
        img.close()
        if img is not source_img:
            source_img.close()
        temp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Optimize files for PaddleOCR document parsing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Optimize image with default quality (85)
  python scripts/optimize_file.py input.png output.png

  # Optimize with specific quality
  python scripts/optimize_file.py input.jpg output.jpg --quality 70

Supported formats:
  - Images: PNG, JPG, JPEG, BMP, TIFF, TIF
        """,
    )

    parser.add_argument("input", help="Input file path")
    parser.add_argument("output", help="Output file path")
    parser.add_argument(
        "--quality", type=int, default=85, help="JPEG quality (1-100, default: 85)"
    )
    parser.add_argument(
        "--target-size",
        type=float,
        default=20,
        help=f"Target maximum size in MB (default: 20, max: {MAX_TARGET_SIZE_MB})",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing output image")

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    # Validate input
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    # Determine file type
    ext = input_path.suffix.lower()

    if ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]:
        try:
            output_path = optimize_image(
                input_path,
                output_path,
                args.quality,
                args.target_size,
                force=args.force,
            )
        except (ValueError, RuntimeError, OutputPathError, OSError) as e:
            print(f"ERROR: {e}")
            sys.exit(1)
    elif ext == ".pdf":
        print("ERROR: PDF optimization is not supported by optimize_file.py")
        print("Use one of these instead:")
        print("  - Parse the PDF directly with: python scripts/vl_caller.py --file-path \"input.pdf\" --pretty")
        print("  - Use --file-url for large PDFs to avoid local base64 overhead")
        print("  - Use split_pdf.py if you need to process specific page ranges")
        sys.exit(1)
    else:
        print(f"ERROR: Unsupported file format: {ext}")
        print("Supported: PNG, JPG, JPEG, BMP, TIFF, TIF")
        sys.exit(1)

    print(f"\nOptimized file saved to: {output_path}")
    print("\nYou can now process with:")
    print(f'  python scripts/vl_caller.py --file-path "{output_path}" --pretty')


if __name__ == "__main__":
    main()
