# ─── BUILD STAGE ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /build

# Copy metadata and source code to build the wheel
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Build a standard production wheel (.whl) package
RUN uv build --wheel --out-dir /dist


# ─── PRODUCTION STAGE ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Bring in static ffmpeg
COPY --from=mwader/static-ffmpeg:latest /ffmpeg /usr/local/bin/ffmpeg

# Environment variables for production performance
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Create a non-privileged system user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Copy the built wheel from the builder stage
COPY --from=builder /dist/*.whl /tmp/

# Install the production wheel and gunicorn via standard pip
# This extracts everything statically into site-packages. No dev tools/uv left behind.
RUN pip install --no-cache-dir /tmp/*.whl gunicorn && \
    rm -rf /tmp/*

# Secure the application directory permissions
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

# Run with Gunicorn instead of Flask's dev server.
# 4 workers handle concurrent API/recording requests smoothly.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "simple_stream_recorder.app:create_app()"]
