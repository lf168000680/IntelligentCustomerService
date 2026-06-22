FROM python:3.11-slim

WORKDIR /app

# Python 依赖 - 不安装 curl (避免网络问题)
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple || \
    pip install --no-cache-dir -r requirements.txt

# 拷贝整个项目
COPY . .

ENV PYTHONPATH=/app

EXPOSE 8800

CMD ["python", "-m", "server.main"]
