FROM python:3.11-slim

WORKDIR /app

# Python 依赖 — 多个镜像源容错
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    --retries 5 --timeout 120 \
    || pip install --no-cache-dir -r requirements.txt \
    --retries 5 --timeout 120 \
    || pip install --no-cache-dir -r requirements.txt

# 拷贝整个项目
COPY . .

ENV PYTHONPATH=/app

EXPOSE 8800

CMD ["python", "-m", "server.main"]
