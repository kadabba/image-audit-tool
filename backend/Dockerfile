FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app and frontend
COPY backend/app ./app
COPY frontend ./frontend

# Create data directory for SQLite
RUN mkdir -p /app/data

# Expose port
EXPOSE 8000

# Run uvicorn
# --proxy-headers: брать реальный IP клиента из X-Forwarded-For.
# Доверяем всем источникам, т.к. порт в compose открыт только на 127.0.0.1 —
# дотянуться может лишь локальный реверс-прокси.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
