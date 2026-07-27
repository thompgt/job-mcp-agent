# The API image. The MCP server is normally run by the host over stdio, not
# in a container, so this builds the HTTP surface.
#
# Two stages: the first builds a wheel, the second installs only that wheel.
# Nothing from the build stage — no source tree, no build backend, no cache —
# reaches the runtime image.

FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN uv build --wheel --out-dir /dist


FROM python:3.12-slim AS runtime

# Tesseract and poppler back the [ocr] extra. They are the only system
# packages needed; everything else is pure Python.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

# A non-root user with a home directory, because platformdirs resolves the
# data directory relative to $HOME and a user without one lands in /.
RUN useradd --create-home --uid 10001 careercraft

COPY --from=build /dist/*.whl /tmp/
RUN uv pip install --system --no-cache /tmp/*.whl'[pdf,ocr,api]' \
 && rm /tmp/*.whl

# 0.0.0.0 is required for published ports to reach the process at all. The
# unauthenticated-bind opt-out is set here rather than the guard being
# weakened, so running this outside a container network is still a decision
# someone has to make on purpose. Set CAREERCRAFT_AUTH_TOKEN if the port is
# published anywhere but localhost.
ENV CAREERCRAFT_DATA_DIR=/data \
    CAREERCRAFT_HOST=0.0.0.0 \
    CAREERCRAFT_PORT=8000 \
    CAREERCRAFT_ALLOW_UNAUTHENTICATED_BIND=1 \
    PYTHONUNBUFFERED=1
RUN mkdir -p /data && chown careercraft:careercraft /data
VOLUME ["/data"]

USER careercraft
EXPOSE 8000

# Hits a route the app actually serves. The v1 compose file healthchecked
# "/mcp" and "/", neither of which existed, so the service reported unhealthy
# forever while working perfectly.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["careercraft", "api"]
