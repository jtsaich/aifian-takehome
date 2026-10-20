# Production image. The same image serves the web app (default CMD) and runs
# `bakery-init` (migrate + seed) as a one-off: a Cloud Run job in production,
# the `init` service in compose.yaml locally.

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Dependencies first so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
# Non-editable: the venv holds the package itself, so the runtime stage needs only .venv.
RUN uv sync --frozen --no-dev --no-editable


# Same base Python as the build stage (the uv image is built on python:3.13-slim-bookworm),
# so the venv's interpreter symlink resolves.
FROM python:3.13-slim-bookworm

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin bakery
WORKDIR /app
COPY --from=build --chown=root:root /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8080

USER bakery
EXPOSE 8080

# Cloud Run sets PORT and terminates TLS in front of the container; trust its
# X-Forwarded-* headers so generated URLs and redirects use https.
CMD ["sh", "-c", "exec uvicorn --factory bakery.web.app:create_app --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips '*'"]
