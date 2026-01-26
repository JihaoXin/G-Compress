#!/usr/bin/env python3
"""
PDF 转图像脚本

用法:
    python scripts/pdf_to_images.py Latex/main.pdf
    python scripts/pdf_to_images.py Latex/main.pdf --dpi 200 --output-dir Latex/pages

输出:
    Latex/page_0.png, Latex/page_1.png, ...
"""

import argparse
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("请安装 PyMuPDF: pip install PyMuPDF")
    sys.exit(1)


def pdf_to_images(
    pdf_path: str,
    output_dir: str = None,
    dpi: int = 150,
    prefix: str = "page"
) -> list[str]:
    """
    将 PDF 转换为 PNG 图像

    Args:
        pdf_path: PDF 文件路径
        output_dir: 输出目录，默认与 PDF 同目录
        dpi: 分辨率，默认 150
        prefix: 文件名前缀

    Returns:
        生成的图像文件路径列表
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # 输出目录
    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = pdf_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    # 打开 PDF
    doc = fitz.open(str(pdf_path))
    images = []

    # 计算缩放比例 (72 DPI 是 PDF 默认)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    print(f"Converting {pdf_path} ({doc.page_count} pages) at {dpi} DPI...")

    for page_num in range(doc.page_count):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=matrix)

        # 保存图像
        img_path = out_dir / f"{prefix}_{page_num}.png"
        pix.save(str(img_path))
        images.append(str(img_path))
        print(f"  Saved: {img_path}")

    doc.close()
    print(f"Done! Generated {len(images)} images.")
    return images


def main():
    parser = argparse.ArgumentParser(description="Convert PDF to images")
    parser.add_argument("pdf", help="PDF file path")
    parser.add_argument("--output-dir", "-o", help="Output directory")
    parser.add_argument("--dpi", "-d", type=int, default=150, help="Resolution (default: 150)")
    parser.add_argument("--prefix", "-p", default="page", help="Output filename prefix")
    args = parser.parse_args()

    try:
        images = pdf_to_images(
            args.pdf,
            output_dir=args.output_dir,
            dpi=args.dpi,
            prefix=args.prefix
        )
        # 输出图像路径列表（用于脚本调用）
        print("\nGenerated images:")
        for img in images:
            print(img)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
