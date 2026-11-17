FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN groupadd --gid 10001 pricing \
    && useradd --uid 10001 --gid pricing --no-create-home pricing \
    && install -d -o pricing -g pricing /app/.data /data
COPY main.py .

USER pricing
EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
