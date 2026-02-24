#!/bin/bash
set -e

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
fi


# Run pre-commit checks
if [ -f ".pre-commit-config.yaml" ]; then
    echo "Running pre-commit..."
    pre-commit run --all-files
fi

# Run tests
echo "Running tests..."
python parse_projects_test.py

# Run the parser
python parse_projects.py "$@"

# Generate the report
python generate_report.py
