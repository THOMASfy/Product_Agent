#!/usr/bin/env bash
# 在**服务器/容器**上安装文件生成依赖（PPT/Word/Excel/PDF）。
# 用户端不需要执行任何命令；他们只用飞书。
#
# 用法（Debian/Ubuntu，需 root 或 sudo）：
#   sudo bash connect_to_feishu/deploy/setup-linux.sh
set -euo pipefail

SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

echo "==> 安装系统依赖（LibreOffice / Python / Poppler / 中文字体）"
$SUDO apt-get update
$SUDO apt-get install -y --no-install-recommends \
  libreoffice \
  python3 python3-pip \
  poppler-utils \
  fonts-noto-cjk \
  ca-certificates

echo "==> 安装 Python 文件生成库"
# 某些发行版启用了 PEP 668，需要 --break-system-packages；旧版本可忽略该参数。
$SUDO pip3 install --no-cache-dir --break-system-packages \
  python-pptx python-docx openpyxl pdf2image Pillow

echo "==> 校验"
python3 -c "import pptx, docx, openpyxl, PIL; print('python libs OK')"
(command -v soffice >/dev/null && soffice --version) || echo "警告：未找到 soffice"

echo "完成。启动连接器时会在日志里打印「文件生成能力」自检结果。"
