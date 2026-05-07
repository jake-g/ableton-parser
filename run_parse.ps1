# Set strict error handling
$ErrorActionPreference = "Stop"

$Host.UI.RawUI.WindowTitle = "ableton-project-parser"
Set-Location "D:\Music Production\ableton projects"

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

Write-Host "Staging and committing updates to Git..."
# Stage all project data, cache, and code changes
git add README.md generate_report.py REPORT.md Makefile zip_skeleton.py outputs/ projects.tsv run_parse.ps1
# Stage any modified personal project folders/skeletons
git add _*
git add "* Project"

# Generate current timestamp and commit
$DateStr = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
git commit -m "Run parse update on $DateStr"

Write-Host "Done!"
pause
