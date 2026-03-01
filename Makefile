.PHONY: help setup test lint run build install-usb clean

PYTHON ?= python3
PIP ?= pip3
VENV := .venv
VENV_BIN := $(VENV)/bin

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Set up development environment
	$(PYTHON) -m venv $(VENV)
	$(VENV_BIN)/pip install --upgrade pip
	$(VENV_BIN)/pip install -r requirements.txt
	@echo "Activate with: source $(VENV)/bin/activate"

test: ## Run tests
	$(VENV_BIN)/python -m pytest tests/ -v

lint: ## Run linter
	$(VENV_BIN)/python -m flake8 src/ --max-line-length=120

run: ## Run the web application (development)
	$(VENV_BIN)/python -m src.core.app

build: ## Build bootable ISO image
	bash scripts/build_iso.sh

install-usb: ## Install to USB drive (requires USB_DEV variable)
ifndef USB_DEV
	$(error USB_DEV is not set. Usage: make install-usb USB_DEV=/dev/sdX)
endif
	bash scripts/install_to_usb.sh $(USB_DEV)

clean: ## Clean build artifacts
	rm -rf build/ dist/ *.iso
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true
