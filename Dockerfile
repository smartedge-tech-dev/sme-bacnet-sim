# Multi-arch image: linux/amd64, linux/arm64, linux/arm/v7.
# Some dependencies have no wheel for every architecture (e.g. armv7l), so they are built
# in a builder stage with a compiler; the final stage only gets the installed packages.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libyaml-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --prefix=/install -r /tmp/requirements.txt


FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app

# libyaml for the PyYAML C extension when it was compiled in the builder stage;
# tzdata so `-e TZ=Asia/Tokyo` sets the clock that schedules and the UI use (default: UTC)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libyaml-0-2 tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app
COPY sme_bacnet_sim ./sme_bacnet_sim
COPY configs ./configs
# `sme-bacnet-sim ...` works in the image too (e.g. `sme-bacnet-sim clone ...`), from any working directory
RUN printf '#!/bin/sh\nexec python -m sme_bacnet_sim "$@"\n' > /usr/local/bin/sme-bacnet-sim \
    && chmod +x /usr/local/bin/sme-bacnet-sim

# Run as an unprivileged user
RUN useradd --create-home --uid 10001 sim && chown -R sim /app
USER sim

# Web UI and BACnet/IP
EXPOSE 8080
EXPOSE 47808/udp

# Note: BACnet broadcast (Who-Is) does not cross Docker bridge networks;
# use --network host on Linux or publish 47808/udp for unicast.
CMD ["python", "-m", "sme_bacnet_sim", "-c", "configs/demo-building.yaml", "--host", "0.0.0.0", "--port", "8080"]
