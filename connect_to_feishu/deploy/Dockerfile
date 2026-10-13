# 服务器端运行环境（可选）。
# 构建上下文 = 仓库根目录（含 opencode.jsonc、.opencode、data、connect_to_feishu）。
#
#   docker build -f connect_to_feishu/deploy/Dockerfile -t plm-feishu .
#   docker run --rm -v "$PWD/data:/app/data" --env-file connect_to_feishu/.env plm-feishu
#
FROM node:22-bookworm

# 文件生成依赖（只装在服务器/容器里）：LibreOffice + Python 库 + 中文字体。
RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice \
      python3 python3-pip \
      poppler-utils \
      fonts-noto-cjk \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages \
      python-pptx python-docx openpyxl pdf2image Pillow

# OpenCode CLI：连接器用它在本机拉起 OpenCode 后台服务。
RUN npm install -g @opencode/cli

WORKDIR /app

# 连接器依赖
COPY connect_to_feishu/package.json connect_to_feishu/package-lock.json* ./connect_to_feishu/
RUN cd connect_to_feishu && npm install

# 整个仓库：opencode.jsonc、.opencode（agents/skills）、data
COPY . .

ENV NODE_ENV=production
WORKDIR /app/connect_to_feishu
CMD ["npx", "tsx", "src/index.ts"]
