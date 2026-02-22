.DEFAULT_GOAL := help

VERSION = $(shell cat VERSION)

app_root := $(CURDIR)
pkg_src = $(app_root)/src/twsrt
tests_src = $(app_root)/tests

################################################################################
# Testing \
TESTING:  ## ############################################################

.PHONY: test
test: test-unit  ## run tests

.PHONY: test-unit
test-unit:  ## run all tests except "integration" marked
	RUN_ENV=local uv run python -m pytest -m "not (integration or experimentation)" --cov-config=pyproject.toml --cov-report=html --cov-report=term --cov=$(pkg_src) tests

################################################################################
# Code Quality \
QUALITY:  ## ############################################################

.PHONY: format
format:  ## perform ruff formatting
	@uv run ruff format $(pkg_src) $(tests_src)

.PHONY: lint
lint:  ## check style with ruff
	uv run ruff check --fix $(pkg_src) $(tests_src)

.PHONY: ty
ty:  ## check type hint annotations
	@uvx ty check $(pkg_src)

.PHONY: static-analysis
static-analysis: lint format ty  ## run all static analysis

.PHONY: pre-commit-install
pre-commit-install:  ## install pre-commit hooks
	uv run pre-commit install

################################################################################
# Building, Deploying \
BUILDING:  ## ############################################################

.PHONY: all
all: clean build publish  ## Build and publish to PyPI

.PHONY: build
build: clean format  ## format and build
	uv build

.PHONY: publish
publish:  ## publish to PyPI
	uv run twine upload --verbose dist/*

.PHONY: install
install:  ## install as uv tool
	uv tool install -e .
	twsrt --install-completion bash 2>/dev/null || true

.PHONY: uninstall
uninstall:  ## uninstall uv tool
	uv tool uninstall twsrt

.PHONY: bump-major
bump-major: check-github-token  ## bump-major, tag and push
	uv run bump-my-version bump --commit --tag major
	git push && git push --tags
	@$(MAKE) create-release

.PHONY: bump-minor
bump-minor: check-github-token  ## bump-minor, tag and push
	uv run bump-my-version bump --commit --tag minor
	git push && git push --tags
	@$(MAKE) create-release

.PHONY: bump-patch
bump-patch: check-github-token  ## bump-patch, tag and push
	uv run bump-my-version bump --commit --tag patch
	git push && git push --tags
	@$(MAKE) create-release

.PHONY: create-release
create-release: check-github-token  ## create a release on GitHub via the gh cli
	@command -v gh >/dev/null || { echo "gh CLI not installed"; exit 1; }
	@echo "Creating GitHub release for v$(VERSION)"
	gh release create "v$(VERSION)" --generate-notes --latest

.PHONY: check-github-token
check-github-token:
	@if [ -z "$$GITHUB_TOKEN" ]; then \
		echo "GITHUB_TOKEN is not set. Please export your GitHub token before running this command."; \
		exit 1; \
	fi
	@echo "GITHUB_TOKEN is set"

################################################################################
# Clean \
CLEAN:  ## ############################################################

.PHONY: clean
clean: clean-build clean-pyc  ## remove all build, test, coverage and Python artifacts

.PHONY: clean-build
clean-build:
	rm -fr build/ dist/ .eggs/
	find . \( -path ./env -o -path ./venv -o -path ./.env -o -path ./.venv \) -prune -o -name '*.egg-info' -exec rm -fr {} +
	find . \( -path ./env -o -path ./venv -o -path ./.env -o -path ./.venv \) -prune -o -name '*.egg' -exec rm -f {} +

.PHONY: clean-pyc
clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

################################################################################
# Misc \
MISC:  ## ############################################################

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z0-9_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("\033[36m%-20s\033[0m %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

.PHONY: help
help:
	@uv run python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)
