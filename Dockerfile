FROM node:22-slim AS frontend-build
WORKDIR /src
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY index.html vite.config.ts tsconfig.json tailwind.config.js postcss.config.js ./
COPY frontend ./frontend
COPY public ./public
RUN pnpm install --frozen-lockfile && pnpm build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=3000
WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt && useradd --create-home forgeiq
COPY alembic.ini /app/alembic.ini
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY --from=frontend-build /src/frontend/dist /app/frontend/dist
RUN mkdir -p /app/backend/data && chown -R forgeiq:forgeiq /app
USER forgeiq
EXPOSE 3000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000}"]
