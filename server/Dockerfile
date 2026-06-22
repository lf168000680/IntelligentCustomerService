FROM python:3.11-slim

WORKDIR /app

# 系统依赖 (Playwright 需要)
RUN apt-get update && apt-get install -y \
    curl \
    libnss3 \
    libnspr4 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright 浏览器
RUN playwright install chromium
RUN playwright install-deps chromium

# 应用代码
COPY . .

# 配置文件
COPY ../config /app/config

# 启动
EXPOSE 8800
CMD ["python", "main.py"]
