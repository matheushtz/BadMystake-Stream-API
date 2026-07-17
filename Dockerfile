FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} app:app"]
