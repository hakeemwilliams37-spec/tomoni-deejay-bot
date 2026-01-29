FROM python:3.11-slim

RUN apt-get update && apt-get install -y --وڑno-install-recommends \
    ffmpeg \
    libopus0 \
    ca-certificates \
    tzdata \
    nodejs \
 && rm -rf /var/lib/apt/lists/*


WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]

