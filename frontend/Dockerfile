# ---- dependencies ----
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---- build ----
FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---- runtime (standalone server, no node_modules tree) ----
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    API_INTERNAL_URL=http://api:8000
RUN addgroup -S terraproof && adduser -S -G terraproof -u 10001 terraproof
COPY --from=build --chown=terraproof:terraproof /app/.next/standalone ./
COPY --from=build --chown=terraproof:terraproof /app/.next/static ./.next/static
COPY --from=build --chown=terraproof:terraproof /app/public ./public
USER terraproof
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=5s --retries=12 \
  CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["node", "server.js"]
