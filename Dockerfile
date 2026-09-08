# syntax=docker/dockerfile:1

# ==========================================================================
# Stage 1 — builder: resolve and install production dependencies into a venv.
# ==========================================================================
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN python -m venv "$VIRTUAL_ENV"

WORKDIR /code

# Only requirements.txt is copied here. requirements-dev.txt (linters, pytest)
# is never installed, so no test tooling ends up in the runtime image.
COPY requirements.txt ./
# --index-url is spelled out so the build can never drift onto a private index
# picked up from the environment: this project installs from public PyPI only.
RUN pip install --upgrade pip \
    && pip install --index-url https://pypi.org/simple -r requirements.txt

# ==========================================================================
# Stage 2 — runtime: copy the venv and the app only. No tests, no dev deps.
# ==========================================================================
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Never run the app as root.
RUN useradd --create-home --uid 1000 appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /code
# Only the application package is shipped — `test/` is deliberately absent, so
# the prod image carries no test code (the whole point of the two stages).
COPY ./app /code/app

USER appuser

EXPOSE 80
# One process, no --workers: the session pool lives in memory, so N workers
# would mean N diverging pools and a wrong rate-limit accounting — which gets
# accounts banned. Scaling out requires moving the pool state to Redis first
# (CLAUDE.md §7).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
