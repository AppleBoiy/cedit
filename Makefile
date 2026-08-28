.DEFAULT_GOAL := help
.PHONY: help run test build-app build-cli build install-app install-cli install clean release

help: ## Show this list
	@echo "cedit - available targets:"
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

run: ## Launch the GUI (python3 cedit.py) - needs PySide6 (pip install -r requirements.txt)
	python3 cedit.py

test: ## Run the full test suite (no PySide6 needed)
	python3 -m unittest discover -s tests -v

build-app: ## Build dist/cedit.app (macOS only - see packaging/build_app.sh)
	./packaging/build_app.sh

build-cli: ## Build the standalone dist/cedit-cli binary (see packaging/build_cli.sh)
	./packaging/build_cli.sh

build: build-app build-cli ## Build both dist/cedit.app and dist/cedit-cli

install-app: ## Build (if needed) and install cedit.app into /Applications (macOS only)
	./packaging/install_app.sh

install-cli: ## Install cedit-cli onto PATH (prebuilt binary if present, else cli.py's source)
	./packaging/install_cli.sh

install: install-app install-cli ## Install both the app and the CLI

clean: ## Remove build artifacts (build/, dist/, .venv-build/, __pycache__/) - never touches your saves
	rm -rf build dist .venv-build
	find . -name '__pycache__' -not -path './.venv/*' -exec rm -rf {} +

release: ## Tag and explain how to push a release - usage: make release VERSION=1.5.0
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make release VERSION=1.5.0" >&2; exit 1; \
	fi
	git tag -a "v$(VERSION)" -m "v$(VERSION)"
	@echo
	@echo "Tagged v$(VERSION) locally. Push it to trigger the release build:"
	@echo "    git push origin v$(VERSION)"
