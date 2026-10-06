FROM python:3.12-slim

# HF_HOME: where faster-whisper stores the speech model (a named volume keeps it between runs)
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 IN_DOCKER=1 HF_HOME=/app/models/hf

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-local.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Mode 2 (local) also needs faster-whisper. docker-compose sets WITH_LOCAL=1 for that service only.
ARG WITH_LOCAL=0
RUN if [ "$WITH_LOCAL" = "1" ]; then pip install --no-cache-dir -r requirements-local.txt; fi

COPY . .
RUN useradd -m -u 1000 appuser && mkdir -p outputs models && chown -R appuser /app
USER appuser

EXPOSE 7860
CMD ["python", "app.py", "--port", "7860"]