# Makefile for Ableton Project Parser
# Supports macOS, Linux, and Windows (via Git Bash / MSYS2 / WSL).
# Recipes stay POSIX-sh friendly: no GNU-only flags, no sed -i, no realpath.

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

OUTPUT_DIR := outputs
SAMPLES_TSV := $(OUTPUT_DIR)/samples.tsv
PROJECTS_TSV := $(OUTPUT_DIR)/projects.tsv

.PHONY: help setup format test run report samples notebook clean \
        private-status private-add private-commit private-push verify-private

# `make` with no arguments prints the help.
.DEFAULT_GOAL := help

help:
	@echo "========================================================================"
	@echo "Ableton Project Parser - Makefile Commands"
	@echo "========================================================================"
	@echo "Available commands:"
	@echo "  make help           - Show this message (default target)"
	@echo "  make setup          - Create the .venv and install dependencies"
	@echo "  make format         - Run pre-commit styling and formatting checks"
	@echo "  make test           - Run the unit test suite"
	@echo "  make run            - Parse projects and generate REPORT.md"
	@echo "  make report         - Regenerate REPORT.md from the parse cache"
	@echo "  make samples        - Summarize $(SAMPLES_TSV)"
	@echo "  make notebook       - Start a Jupyter server with Colab options"
	@echo "  make clean          - Remove generated outputs, logs and caches"
	@echo ""
	@echo "Variables for 'make run':"
	@echo "  root=/path/to/projects  Directory to scan            (default: .)"
	@echo "  probe=1                 Add --probe-samples          (default: off)"
	@echo "  midi=1                  Add --include-midi-clips     (default: off)"
	@echo "  json=                   Unset to skip --save-json    (default: on)"
	@echo ""
	@echo "Variables for 'make samples':"
	@echo "  top=20                  Rows to show in each ranking (default: 10)"
	@echo ""
	@echo "Privacy boundary and private data repository (.private_git):"
	@echo "  make verify-private - Assert no private file can reach public GitHub"
	@echo "  make private-status - Status of the private data repo"
	@echo "  make private-add    - Stage data artifacts into the private repo"
	@echo "  make private-commit - Commit data artifacts to the private repo"
	@echo "  make private-push   - Push the private repo to the Gitea remote"
	@echo "========================================================================"

# Setup virtual environment and dependencies
setup:
	@echo "Setting up virtual environment..."
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
	@echo "Environment setup completed successfully."

# Format and lint codebase using pre-commit
format: setup
	@echo "Running style and formatting checks..."
	@$(PRECOMMIT) run --all-files
	@echo "All style checks passed."

# Run unit tests
test: setup
	@echo "Running unit tests..."
	@$(PYTHON) parse_projects_test.py
	@echo "All tests passed."

# Run full parsing cycle
root ?= .
probe ?=
midi ?=
json ?= 1
PARSE_FLAGS :=
ifneq ($(probe),)
  PARSE_FLAGS += --probe-samples
endif
ifneq ($(midi),)
  PARSE_FLAGS += --include-midi-clips
endif
ifneq ($(json),)
  PARSE_FLAGS += --save-json
endif

run: setup
	@echo "Running Ableton Project Parser on root: $(root)..."
	@$(PYTHON) parse_projects.py --root "$(root)" $(PARSE_FLAGS)
	@echo "Generating detailed report..."
	@$(PYTHON) generate_report.py
	@echo "Finished. See REPORT.md for details."

# Regenerate report from cached parse data
report: setup
	@echo "Regenerating detailed report..."
	@$(PYTHON) generate_report.py
	@echo "REPORT.md has been updated."

# Summarize the sample table. Pure awk so it works without the venv.
top ?= 10

samples:
	@if [ ! -f "$(SAMPLES_TSV)" ]; then \
		echo "$(SAMPLES_TSV) not found. Run 'make run' first."; \
		exit 1; \
	fi
	@echo "=== $(SAMPLES_TSV) ==="
	@awk -F'\t' 'END { printf "Rows: %d\n", NR - 1 }' "$(SAMPLES_TSV)"
	@echo ""
	@echo "Columns:"
	@awk -F'\t' 'NR == 1 { for (i = 1; i <= NF; i++) printf "  %2d. %s\n", i, $$i; exit }' "$(SAMPLES_TSV)"
	@echo ""
	@echo "By source:"
	@awk -F'\t' -v col=source 'NR == 1 { for (i = 1; i <= NF; i++) if ($$i == col) c = i; next } c { n[$$c]++ } END { for (k in n) printf "  %8d  %s\n", n[k], k }' "$(SAMPLES_TSV)" | sort -rn
	@echo ""
	@echo "Top $(top) extensions:"
	@awk -F'\t' -v col=extension 'NR == 1 { for (i = 1; i <= NF; i++) if ($$i == col) c = i; next } c && $$c != "" { n[$$c]++ } END { for (k in n) printf "  %8d  %s\n", n[k], k }' "$(SAMPLES_TSV)" | sort -rn | head -n $(top)
	@echo ""
	@echo "Top $(top) projects by sample count:"
	@awk -F'\t' -v col=project 'NR == 1 { for (i = 1; i <= NF; i++) if ($$i == col) c = i; next } c && $$c != "" { n[$$c]++ } END { for (k in n) printf "  %8d  %s\n", n[k], k }' "$(SAMPLES_TSV)" | sort -rn | head -n $(top)
	@echo ""
	@echo "First 3 rows:"
	@head -n 4 "$(SAMPLES_TSV)" | cut -c 1-160

# Start Jupyter Notebook server
notebook: setup
	@echo "Starting Jupyter Notebook server for Google Colab..."
	@$(JUPYTER) notebook \
		--NotebookApp.allow_origin='https://colab.research.google.com' \
		--port=8888 \
		--NotebookApp.port_retries=0 \
		--NotebookApp.allow_credentials=True

# Private in-place data repository targets
PRIVATE_GIT := git --git-dir=.private_git --work-tree=.

# Paths that must never reach the public GitHub remote.
PRIVATE_PATHS := REPORT.md ableton_projects.ipynb outputs sp404

# Filename patterns that must never be tracked publicly. Used with
# `git ls-files`, so these are gitignore-style globs, not regexes.
PRIVATE_GLOBS := REPORT.md '*.ipynb' 'outputs/*' '*.tsv' '*.pkl' '*.als' \
                 '*.wav' '*.aif' '*.aiff' '*.mp3' '*.flac' '*.m4a' '*.asd' \
                 '*.png' 'counters.json' 'TODO*' 'PLAN*' 'sp404/*'

# Fails if anything private is tracked by, or would be staged into, the
# public repo. Run this before every public push.
verify-private:
	@echo "Verifying public/private separation..."
	@echo "1. Nothing private is tracked by the public repo:"
	@tracked=`git ls-files -- $(PRIVATE_GLOBS)`; \
	if [ -n "$$tracked" ]; then \
		echo "   FAIL - the public repo tracks private files:"; \
		echo "$$tracked" | sed 's/^/     /'; \
		exit 1; \
	fi; \
	echo "   OK - no reports, outputs, media, notebooks, tsv or TODO/PLAN"
	@echo "2. Private paths are ignored by the public repo:"
	@for f in $(PRIVATE_PATHS); do \
		if git check-ignore -q "$$f"; then \
			echo "   OK   - $$f is ignored"; \
		else \
			echo "   FAIL - $$f is NOT ignored; it could be pushed to GitHub"; \
			exit 1; \
		fi; \
	done
	@echo "3. Nothing private would be staged by 'git add -A':"
	@if git add -A --dry-run 2>/dev/null | \
		grep -Ei "\.(als|wav|aiff?|mp3|flac|m4a|tsv|pkl|asd|ipynb|png)$$|(^|/)(REPORT\.md|counters\.json|TODO|PLAN|sp404(/|$$))"; then \
		echo "   FAIL - the files above would be committed publicly"; \
		exit 1; \
	else \
		echo "   OK   - nothing private staged for the public remote"; \
	fi
	@echo "Public/private separation verified."

private-status:
	@$(PRIVATE_GIT) status

private-add:
	@$(PRIVATE_GIT) add .
	@$(PRIVATE_GIT) add -f "**/*.als" "**/*.json" "**/*.png" "REPORT.md" "sp404/**" 2>/dev/null || true

private-commit: private-add
	@$(PRIVATE_GIT) commit -m "update private data" || true

private-push: private-commit
	@$(PRIVATE_GIT) push -u origin main

# Clean up caches, logs, and generated data
clean:
	@echo "Cleaning up temporary files and caches..."
	rm -rf $(OUTPUT_DIR)/plots
	rm -f $(PROJECTS_TSV)
	rm -f $(SAMPLES_TSV)
	rm -f $(OUTPUT_DIR)/counters.json
	rm -f $(OUTPUT_DIR)/parse_projects.log
	rm -rf __pycache__
	rm -rf .ipynb_checkpoints
	rm -rf .mypy_cache
	rm -rf .pytest_cache
	@echo "Note: .venv and $(OUTPUT_DIR)/project_info.pkl were kept."
	@echo "Remove them manually if you want a cold rebuild."
