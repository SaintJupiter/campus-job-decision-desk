.PHONY: install dev test lint build pages evaluate prototype prototype-demo audit-latest audit-baseline init-db import-demo import-latest-private demo-db sync-remote

DEMO_DATABASE_URL=sqlite:///data/demo/public-demo.sqlite
LATEST_SNAPSHOT?=../其他/飞书校招表最新快照.md
BASELINE_SNAPSHOT?=../8.7 飞书列表.md

install:
	python3 -m venv .venv
	.venv/bin/pip install -e '.[dev]'
	npm install

dev:
	npm run dev

test:
	npm test

lint:
	npm run lint

build:
	npm run build

pages: demo-db
	CJD_ENVIRONMENT=public-demo CJD_DATABASE_URL=$(DEMO_DATABASE_URL) .venv/bin/python scripts/export_static_demo.py
	npm run build:pages

evaluate:
	.venv/bin/python scripts/run_evaluation.py

prototype:
	python3 prototypes/logic/app.py

prototype-demo:
	python3 prototypes/logic/app.py --demo

audit-latest:
	python3 scripts/audit_markdown_snapshot.py '$(LATEST_SNAPSHOT)'

audit-baseline:
	python3 scripts/audit_markdown_snapshot.py '$(BASELINE_SNAPSHOT)'

init-db:
	.venv/bin/python scripts/init_db.py

import-demo: init-db
	.venv/bin/python scripts/import_source.py data/demo/source_alpha.csv --source-id demo-alpha --source-name '合成供应商甲' --independence-group demo-alpha --source-kind SYNTHETIC
	.venv/bin/python scripts/import_source.py data/demo/source_beta.tsv --source-id demo-beta --source-name '合成供应商乙' --independence-group demo-beta --source-kind SYNTHETIC

import-latest-private: init-db
	.venv/bin/python scripts/import_source.py '$(LATEST_SNAPSHOT)' --source-id private-list-27-01 --source-name '本地授权校招表' --independence-group private-list-27-01 --source-kind PAID_TABLE

demo-db:
	.venv/bin/python scripts/reset_public_demo_db.py
	CJD_DATABASE_URL=$(DEMO_DATABASE_URL) .venv/bin/python scripts/init_db.py
	CJD_DATABASE_URL=$(DEMO_DATABASE_URL) .venv/bin/python scripts/import_source.py data/demo/source_alpha.csv --source-id demo-alpha --source-name '合成供应商甲' --independence-group demo-alpha --source-kind SYNTHETIC
	CJD_DATABASE_URL=$(DEMO_DATABASE_URL) .venv/bin/python scripts/import_source.py data/demo/source_beta.tsv --source-id demo-beta --source-name '合成供应商乙' --independence-group demo-beta --source-kind SYNTHETIC
	CJD_DATABASE_URL=$(DEMO_DATABASE_URL) .venv/bin/python scripts/seed_demo.py --attest-fresh-reset

sync-remote:
	.venv/bin/python scripts/sync_remote_sources.py
