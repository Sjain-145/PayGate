.PHONY: up down test lint load train migrate

up:
	docker compose up --build -d

down:
	docker compose down -v

migrate:
	alembic upgrade head

train:
	python scripts/train_fraud.py

lint:
	ruff check app tests scripts
	ruff format --check app tests scripts

test:
	docker compose --profile test up -d postgres-test redis-test
	pytest --cov=app --cov-report=term-missing --cov-fail-under=85 -q

load:
	docker run --rm \
		-e API_KEY=$${API_KEY} \
		-e CUSTOMER_ID=$${CUSTOMER_ID} \
		-e BASE_URL=$${BASE_URL:-http://host.docker.internal:8000} \
		-v $(PWD)/loadtest:/scripts grafana/k6 run /scripts/payments.js
