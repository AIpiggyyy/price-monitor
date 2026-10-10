FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY monitor ./monitor
RUN useradd --create-home bot && mkdir -p data && chown -R bot /app
USER bot
# mount your watches.toml, .env and a data/ folder:
#   docker run -d -v $(pwd)/watches.toml:/app/watches.toml -v $(pwd)/data:/app/data --env-file .env price-monitor
CMD ["python", "-m", "monitor", "run", "--config", "watches.toml"]
