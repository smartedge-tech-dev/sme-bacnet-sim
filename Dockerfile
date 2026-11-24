FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY sme_bacnet_sim ./sme_bacnet_sim
COPY configs ./configs

# Run as an unprivileged user
RUN useradd --create-home --uid 10001 sim && chown -R sim /app
USER sim

# Web UI and BACnet/IP
EXPOSE 8080
EXPOSE 47808/udp

# Note: BACnet broadcast (Who-Is) does not cross Docker bridge networks;
# use --network host on Linux or publish 47808/udp for unicast.
CMD ["python", "-m", "sme_bacnet_sim", "-c", "configs/demo-building.yaml", "--host", "0.0.0.0", "--port", "8080"]
