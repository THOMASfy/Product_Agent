#!/usr/bin/env python3
"""把文档渲染成 PDF / 逐页 PNG，便于人工或视觉模型检查效果。

用法:
    python render.py <file> <out_dir> [--png]

流程:
    file --(LibreOffice)--> pdf --(pdf2image/poppler, 仅 --png)--> page-N.png

依赖:
    - LibreOffice (soffice)
    - pdf2image + poppler（仅 --png 时需要，Windows 需把 poppler 的 bin 加入 PATH）
"""
import argparse
import os
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SOFFICE_CANDIDATES = [
    os.environ.get("SOFFICE_PATH", ""),
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "soffice",
]


def find_soffice():
    for candidate in SOFFICE_CANDIDATES:
        if not candidate:
            continue
        if os.sep in candidate or "/" in candidate:
            if os.path.exists(candidate):
                return candidate
        else:
            found = shutil.which(candidate)
            if found:
                return found
    return None


def to_pdf(soffice, source, out_dir):
    subprocess.run(
        [soffice, "--headless", "--norestore", "--convert-to", "pdf", "--outdir", out_dir, source],
        check=True,
        timeout=180,
    )
    pdf = os.path.join(out_dir, os.path.splitext(os.path.basename(source))[0] + ".pdf")
    if not os.path.exists(pdf):
        raise SystemExit(f"pdf not produced: {pdf}")
    return pdf


def pdf_to_png(pdf, out_dir):
    try:
        from pdf2image import convert_from_path
    except ImportError:
        raise SystemExit("pdf2image 未安装：pip install pdf2image Pillow")
    try:
        pages = convert_from_path(pdf, dpi=150)
    except Exception as error:
        raise SystemExit(
            "pdf2image 渲染失败（通常是缺少 poppler）。\n"
            "Windows: 下载 poppler 并把其 bin 目录加入 PATH。\n"
            f"原始错误: {error}"
        )
    outputs = []
    for index, page in enumerate(pages, start=1):
        path = os.path.join(out_dir, f"page-{index}.png")
        page.save(path, "PNG")
        outputs.append(path)
    return outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("out_dir")
    parser.add_argument("--png", action="store_true", help="同时渲染逐页 PNG")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    soffice = find_soffice()
    if not soffice:
        raise SystemExit("未找到 LibreOffice (soffice)，请先安装或设置 SOFFICE_PATH")

    pdf = to_pdf(soffice, args.source, args.out_dir)
    print(f"RENDERED {pdf}")
    if args.png:
        for path in pdf_to_png(pdf, args.out_dir):
            print(f"RENDERED {path}")


if __name__ == "__main__":
    main()
