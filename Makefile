.PHONY: help setup build dev test lint docker-build docker-up docker-down iso clean

help:
	@echo "Distributed SharePoint System - Project Commands"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  make setup              Install dependencies and prepare environment"
	@echo ""
	@echo "Development:"
	@echo "  make dev                Start dev server with hot reload"
	@echo "  make build              Build TypeScript to JavaScript"
	@echo "  make lint               Run ESLint"
	@echo "  make test               Run tests"
	@echo ""
	@echo "Docker & Deployment:"
	@echo "  make docker-build       Build Docker image"
	@echo "  make docker-up          Start all services with docker-compose"
	@echo "  make docker-down        Stop all services"
	@echo "  make docker-logs        View service logs"
	@echo ""
	@echo "ISO & VirtualBox:"
	@echo "  make iso                Build ISO for VirtualBox testing"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean              Clean build artifacts"
	@echo "  make migrate            Run database migrations"

setup:
	npm install
	cp .env.example .env
	npm run build

build:
	npm run build

dev:
	npm run dev

test:
	npm test

lint:
	npm run lint

docker-build:
	docker build -t dss-system:latest .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-clean:
	docker-compose down -v

iso:
	bash scripts/build-iso.sh

migrate:
	npm run migrate

clean:
	rm -rf dist/
	rm -rf node_modules/
	rm -rf build/
	rm -f .env

db-reset:
	docker-compose exec postgres psql -U postgres -d dss -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

db-shell:
	docker-compose exec postgres psql -U postgres -d dss

redis-cli:
	docker-compose exec redis redis-cli

minio-browser:
	@echo "MinIO Admin Console: http://localhost:9001"
	@echo "Username: minioadmin"
	@echo "Password: minioadmin"

health-check:
	@echo "Checking service health..."
	curl -s http://localhost:3000/health | jq .
	@echo ""

vm-test:
	@echo "Testing VM orchestration (requires VirtualBox or KVM)..."
	curl -X GET http://localhost:3000/api/v1/vms \
	  -H "Authorization: Bearer YOUR_TOKEN"

.DEFAULT_GOAL := help
