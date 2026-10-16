FROM node:26-bookworm-slim AS ui
WORKDIR /build
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.15-slim-bookworm
ARG TARGETARCH
ARG MEGACMD_VERSION=2.6.0-2.1
ARG MEGACMD_SHA256=f10bd96dc622a72d91b09ed66ba5a70a6c2ca7df344694b0289cf1685458db14
RUN test "$TARGETARCH" = amd64 \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tini \
    && curl -fsSL "https://mega.nz/linux/repo/Debian_12/amd64/megacmd_${MEGACMD_VERSION}_amd64.deb" -o /tmp/megacmd.deb \
    && echo "$MEGACMD_SHA256  /tmp/megacmd.deb" | sha256sum -c - \
    && apt-get install -y --no-install-recommends /tmp/megacmd.deb \
    && apt-get purge -y curl \
    && rm -rf /var/lib/apt/lists/* /tmp/megacmd.deb \
    && useradd --create-home --uid 10001 app \
    && mkdir /data && chown app:app /data
WORKDIR /app
COPY backend/ ./backend/
COPY --from=ui /build/dist ./web/dist/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENV HOME=/home/app PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
