# Makefile for Ableton Project Parser
# Supports macOS, Linux, and Windows (via Git Bash / MSYS2 / WSL)

# Cross-platform virtual environment binary detection
ifeq ($(OS),Windows_NT)
  VENV_BIN := .venv/Scripts
  PYTHON := $(VENV_BIN)/python.exe
  PRECOMMIT := $(VENV_BIN)/pre-commit.exe
  JUPYTER := $(VENV_BIN)/jupyter.exe
else
  VENV_BIN := .venv/bin
  PYTHON := $(VENV_BIN)/python
  PRECOMMIT := $(VENV_BIN)/pre-commit
  JUPYTER := $(VENV_BIN)/jupyter
endif

.PHONY: help setup format test run report notebook clean

# Default target
help:
	@echo "========================================================================"
	@echo "🎹 Ableton Project Parser - Makefile Commands"
	@echo "========================================================================"
	@echo "Available commands:"
	@echo "  make setup         - Set up python virtual environment and install dependencies"
	@echo "  make format        - Run pre-commit styling and formatting checks"
	@echo "  make test          - Run unit tests"
	@echo "  make run           - Run project parser and generate the report"
	@echo "                       (Optionally specify project root: make run root=/path/to/projects)"
	@echo "  make report        - Regenerate only the detailed REPORT.md"
	@echo "  make notebook      - Start Jupyter Notebook server with Google Colab options"
	@echo "  make clean         - Clean up logs, caches, and generated outputs"
	@echo "========================================================================"

# Setup virtual environment and dependencies
setup:
	@echo "🛠️  Setting up virtual environment..."
	@if [ ! -d ".venv" ]; then \
		python3 -m venv .venv || python -m venv .venv || virtualenv .venv; \
	fi
	@echo "Installing dependencies..."
	@$(PYTHON) -m pip install --upgrade pip
	@$(PYTHON) -m pip install -r requirements.txt
	@if [ -f ".pre-commit-config.yaml" ]; then \
		$(PYTHON) -m pip install pre-commit; \
		$(PRECOMMIT) install; \
	fi
	@echo "✅ Environment setup completed successfully!"

# Format and lint codebase using pre-commit
format: setup
	@echo "🛠️  Running style and formatting checks..."
	@$(PRECOMMIT) run --all-files
	@echo "✅ All style checks passed!"

# Run unit tests
test: setup
	@echo "🧪 Running unit tests..."
	@$(PYTHON) parse_projects_test.py
	@echo "✅ All tests passed!"

# Run full parsing cycle
root ?= .
run: setup
	@echo "🚀 Running Ableton Project Parser on root: $(root)..."
	@$(PYTHON) parse_projects.py --root "$(root)"
	@echo "📊 Generating detailed report..."
	@$(PYTHON) generate_report.py
	@echo "✅ Finished successfully! Check REPORT.md for details."

# Regenerate report from cached parse data
report: setup
	@echo "📊 Regenerating detailed report..."
	@$(PYTHON) generate_report.py
	@echo "✅ REPORT.md has been successfully updated!"

# Start Jupyter Notebook server
notebook: setup
	@echo "📓 Starting Jupyter Notebook server for Google Colab..."
	@$(JUPYTER) notebook \
		--NotebookApp.allow_origin='https://colab.research.google.com' \
		--port=8888 \
		--NotebookApp.port_retries=0 \
		--NotebookApp.allow_credentials=True


# Clean up caches, logs, and generated data
clean:
	@echo "🧹 Cleaning up temporary files and caches..."
	rm -rf outputs/plots
	rm -f outputs/projects.tsv
	rm -f outputs/counters.json
	rm -f outputs/parse_projects.log
	rm -rf __pycache__
	rm -rf .ipynb_checkpoints
	rm -rf .mypy_cache
	rm -rf .pytest_cache
	@echo "Note: .venv was not removed. Remove manually if needed."
