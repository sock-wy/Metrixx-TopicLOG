# Topic Log server: the desktop app's server.py run headless (Coolify / Docker).
# Data lives in /data (mount a volume there); keys come from environment variables; the page asks for TOPICLOG_PASSWORD.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy
ENV PYTHONUNBUFFERED=1 TOPICLOG_SERVER=1 TOPICLOG_HOME=/data/app TOPICLOG_OUT="/data/Topic Log Data" PORT=8765 TZ=America/Chicago
RUN apt-get update && apt-get install -y --no-install-recommends rclone tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt pyyaml openpyxl reportlab pillow playwright==1.47.0 tzdata
COPY . /src
RUN python /src/desktop/server_bundle.py /src /app && rm -rf /src
EXPOSE 8765
VOLUME ["/data"]
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8765')+'/api/health')" || exit 1
CMD ["python", "/app/server.py"]
