FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# opentele requires SIP (C extension) — install separately, non-fatal if it fails
RUN pip install --no-cache-dir --no-build-isolation opentele==1.15.1 || \
    echo "WARNING: opentele install failed — TData import will be unavailable"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
