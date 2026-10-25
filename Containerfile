FROM docker.io/library/debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 libgphoto2-6 ffmpeg v4l-utils ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY runtime.py config.py camera_bridge.py server.py index.html webcam.sh container-entrypoint.sh ./
RUN chmod 755 webcam.sh container-entrypoint.sh
ENV CANON_STUDIO_RUNTIME=container CANON_STUDIO_DATA_DIR=/data \
    XDG_RUNTIME_DIR=/tmp/canon-runtime PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["/app/container-entrypoint.sh"]
CMD ["python3", "/app/server.py"]
