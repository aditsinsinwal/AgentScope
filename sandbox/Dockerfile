FROM python:3.12.3-slim-bookworm

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git ripgrep \
    && pip install --no-cache-dir pytest==8.3.4 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /workspace \
    && chown 65534:65534 /workspace
USER 65534:65534
WORKDIR /workspace
