.PHONY: up down logs migrate test lint proto

up:            ## start everything (bot in polling mode, worker, infra)
	docker compose -f infra/docker-compose.yml up -d --build

down:
	docker compose -f infra/docker-compose.yml down

logs:
	docker compose -f infra/docker-compose.yml logs -f bot worker

migrate:
	docker compose -f infra/docker-compose.yml run --rm migrate

test:
	pytest -q

lint:
	ruff check storybook tests && ruff format --check storybook tests

proto:         ## prototype: photos -> sheet -> 3 scenes -> scores (see scripts/prototype.py)
	python scripts/prototype.py --photos ./proto/photos --out ./proto/out
