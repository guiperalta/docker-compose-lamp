FROM lamp-web:php83

# Same procedure as www-escrybe/DEV_ENV_SETUP.md section 7: GhostScript + WeasyPrint in a shared
# venv at /opt/weasyprint (absolute shebang, independent of $HOME, works for www-data).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ghostscript python3-venv \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
        libcairo2 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/weasyprint \
    && /opt/weasyprint/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/weasyprint/bin/pip install --no-cache-dir weasyprint \
    && chmod -R a+rX /opt/weasyprint \
    && ln -sf /opt/weasyprint/bin/weasyprint /usr/local/bin/weasyprint
