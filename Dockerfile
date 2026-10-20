# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
COPY web/.npmrc ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ARG NICOTINE_VERSION=3.3.6
ARG UID=1000
ARG GID=1000
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    XDG_DATA_HOME=/data XDG_CONFIG_HOME=/config HOME=/tmp \
    NICOTINE_WEBUI_HOST=0.0.0.0 NICOTINE_WEBUI_PORT=8181
RUN groupadd --gid "${GID}" nicotine \
    && useradd --uid "${UID}" --gid nicotine --no-create-home nicotine \
    && apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-deps "nicotine-plus==${NICOTINE_VERSION}"
COPY plugin/ /opt/nicotine-webgui/plugin/
COPY --from=web /build/dist/ /opt/nicotine-webgui/plugin/webgui/static/
COPY docker/entrypoint.sh docker/bootstrap.py /usr/local/bin/
RUN chmod 0755 /usr/local/bin/entrypoint.sh \
    && mkdir -p /data /config /shares \
    && chown nicotine:nicotine /data /config
USER nicotine
EXPOSE 8181 2234/tcp
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8181/api/v1/health', timeout=3)"
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["python", "-m", "pynicotine", "--headless"]
