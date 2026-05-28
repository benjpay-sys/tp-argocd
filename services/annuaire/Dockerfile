# ---- Stage 1 : build / install des dépendances ----
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./

RUN npm ci --only=production

# ---- Stage 2 : image runtime ----
FROM node:20-alpine AS runtime

LABEL org.opencontainers.image.source="https://github.com/Utilisateur/tp-argocd"

WORKDIR /app

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY src/ ./src/

RUN addgroup -g 1001 appgroup && \
    adduser -u 1001 -G appgroup -s /bin/sh -D appuser && \
    chown -R appuser:appgroup /app

USER appuser

ENV PORT=8080 \
    LOG_LEVEL=info \
    NODE_ENV=production

EXPOSE 8080

CMD ["node", "src/index.js"]

