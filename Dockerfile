FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    webp \
    ffmpeg \
    unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY convert.py .

RUN pip install --no-cache-dir "rlottie-python" "Pillow>=10.0"

CMD ["python", "convert.py"]
