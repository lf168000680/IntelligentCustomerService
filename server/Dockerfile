FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies with retries
COPY server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    --retries 10 --timeout 120 \
    || pip install --no-cache-dir -r /app/requirements.txt \
    --retries 10 --timeout 120 \
    || pip install --no-cache-dir -r /app/requirements.txt

# Copy project
COPY . /app/

# Pre-download the embedding model to avoid first-request delay
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')" \
    || echo "Model pre-download skipped (will download on first run)"

ENV PYTHONPATH=/app
ENV POSTGRES_HOST=postgres
ENV REDIS_URL=redis://redis:6379/0
ENV DEBUG=false

EXPOSE 8800

CMD ["python", "-m", "server.main"]
