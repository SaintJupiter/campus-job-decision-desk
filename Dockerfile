FROM node:22-alpine AS web-build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig*.json vite.config.ts eslint.config.js ./
COPY web ./web
RUN npm run build

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CJD_ENVIRONMENT=public-demo \
    CJD_DATABASE_URL=sqlite:///data/demo/public-demo.sqlite

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY data/demo ./data/demo
COPY evaluation ./evaluation
COPY docs/evaluation ./docs/evaluation
COPY --from=web-build /app/dist ./dist

RUN pip install --no-cache-dir . \
    && python scripts/reset_public_demo_db.py \
    && python scripts/init_db.py \
    && python scripts/import_source.py data/demo/source_alpha.csv --source-id demo-alpha --source-name '合成供应商甲' --independence-group demo-alpha --source-kind SYNTHETIC \
    && python scripts/import_source.py data/demo/source_beta.tsv --source-id demo-beta --source-name '合成供应商乙' --independence-group demo-beta --source-kind SYNTHETIC \
    && python scripts/seed_demo.py --attest-fresh-reset

EXPOSE 8000
CMD ["sh", "-c", "uvicorn campus_job_desk.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
