# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
COPY web/.npmrc ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
COPY --from=web /build/dist/ /opt/webui/
COPY --chmod=0644 docker/serve_ui.py /usr/local/bin/serve_ui.py
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
ENTRYPOINT ["python", "/usr/local/bin/serve_ui.py"]
CMD []
