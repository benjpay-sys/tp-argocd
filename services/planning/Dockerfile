# ---- Stage 1 : build / install des dépendances ----
FROM python:3.12-slim AS build

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---- Stage 2 : runtime ----
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.source="https://github.com/Utilisateur/tp-argocd"

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY app/ ./app/

ENV PATH="/opt/venv/bin:$PATH" \
    PORT=8080 \
    LOG_LEVEL=info \
    PYTHONUNBUFFERED=1

RUN groupadd -g 1001 appgroup && \
    useradd -r -u 1001 -g appgroup -d /app appuser && \
    chown -R appuser:appgroup /app

USER appuser

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

