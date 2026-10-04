# Reelsmith — topic / description / link in, 9:16 promo video + captions + cover out.
FROM python:3.12-slim-bookworm

# ffmpeg encodes the video. skia-python's compiled module links against GL/EGL, expat and X11 client libraries
# even for CPU (raster) rendering, so those are needed although nothing is displayed. fontconfig supplies
# /etc/fonts so skia doesn't warn; the app ships its own fonts.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libegl1 libexpat1 libx11-6 fontconfig ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REELSMITH_IN_DOCKER=1 \
    REELSMITH_CONFIG=/data/config/config.json \
    REELSMITH_PORT=5179

WORKDIR /app
# dependencies first so code edits don't reinstall numpy/scipy/skia
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY pyproject.toml README.md LICENSE ./
COPY reelsmith ./reelsmith
COPY examples ./examples
# Headless Chromium for the page scroll-through screenshots (about +450 MB). Build with --build-arg WITH_BROWSER=0 to
# skip it; videos then show the README drawn as a page instead.
ARG WITH_BROWSER=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN if [ "$WITH_BROWSER" = "1" ]; then \
      pip install "playwright>=1.40" && playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*; \
    fi
RUN pip install --no-deps . \
 && python -c "import skia, numpy, scipy; from reelsmith.engine import timeline; print('import ok')"

# unprivileged user; /data holds rendered jobs and saved settings (API keys) and should be a volume
RUN useradd --create-home --uid 1000 reelsmith \
 && mkdir -p /data/output /data/config \
 && chown -R reelsmith:reelsmith /data
USER reelsmith
VOLUME ["/data"]

EXPOSE 5179
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; p=os.environ.get('REELSMITH_PORT','5179'); urllib.request.urlopen(urllib.request.Request(f'http://localhost:{p}/healthz', headers={'Host': f'localhost:{p}'}), timeout=4)" || exit 1

# Listens on all interfaces *inside* the container; compose publishes it on the host's loopback only.
# The port inside and outside must match: the server only answers requests addressed to its own port.
CMD ["sh", "-c", "exec reelsmith serve --host 0.0.0.0 --port \"$REELSMITH_PORT\" --out /data/output"]
