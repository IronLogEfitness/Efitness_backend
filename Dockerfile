# syntax=docker/dockerfile:1

# ---- Base image -------------------------------------------------------------
# Start from an official Python 3.12 image. The "-slim" variant is a trimmed-down
# Debian with just enough to run Python — much smaller than the full image.
FROM python:3.12-slim

# ---- Python runtime behaviour ----------------------------------------------
# PYTHONDONTWRITEBYTECODE: don't litter the image with .pyc files.
# PYTHONUNBUFFERED: send stdout/stderr straight to the console (no buffering),
# so container logs show up immediately in `docker logs` / Azure Log Stream.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ---- Working directory ------------------------------------------------------
# All following commands run from /app inside the image's filesystem.
WORKDIR /app

# ---- Dependencies (cached layer) -------------------------------------------
# Copy ONLY requirements.txt first, then install. Because this layer only
# changes when requirements.txt changes, Docker reuses the cached install on
# every rebuild where deps are unchanged — so editing app code rebuilds fast.
# --no-cache-dir keeps pip's download cache out of the image (smaller image).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Application code -------------------------------------------------------
# Now copy the rest of the project. This is the layer that changes most often.
COPY . .

# ---- Non-root user ----------------------------------------------------------
# Create an unprivileged user and hand it ownership of /app, then switch to it.
# If the app is ever compromised, the attacker isn't root inside the container.
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

# ---- Network ----------------------------------------------------------------
# Documents that the app listens on 8000. EXPOSE is metadata/documentation;
# it does not actually publish the port — `docker run -p` does that.
EXPOSE 8000

# ---- Start command ----------------------------------------------------------
# Production start: NO --reload. Bind 0.0.0.0 so the server is reachable from
# outside the container. Listen on $PORT if the platform injects one (Azure App
# Service does), otherwise default to 8000 — so the same image runs unchanged
# locally and on Azure. `sh -c` lets the shell expand ${PORT:-8000}.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
