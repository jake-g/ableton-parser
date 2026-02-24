# Set strict error handling
$ErrorActionPreference = "Stop"

$Host.UI.RawUI.WindowTitle = "ableton-project-parser"

# Assume python is available in path or .venv already active/available
$Python = "python"
Write-Host "Using Python: $Python"

Write-Host "Updating requirements..."
& $Python -m pip install -r requirements.txt

Write-Host "Running pre-commit..."
& $Python -m pre_commit run --all-files

Write-Host "Running tests..."
& $Python parse_projects_test.py

Write-Host "Running parser..."
# Use Tee-Object to capture log while showing output, mirroring user's preference
& $Python parse_projects.py $args | Tee-Object -FilePath "outputs/parse_projects.log"

Write-Host "Generating report..."
& $Python generate_report.py

Write-Host "Done!"
pause
