FROM lamp-web:php83

# ghostscript + python/pip; pango/harfbuzz are weasyprint's native deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        ghostscript python3-pip \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*

# bookworm marks system python "externally managed" (PEP 668)
RUN pip3 install --no-cache-dir --break-system-packages weasyprint
