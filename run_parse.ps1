# Set strict error handling
$ErrorActionPreference = "Stop"

$Host.UI.RawUI.WindowTitle = "ableton-project-parser"
Set-Location $PSScriptRoot

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
& $Python parse_projects.py --save-json $args | Tee-Object -FilePath "outputs/parse_projects.log"

Write-Host "Generating report..."
& $Python generate_report.py

Write-Host "Staging and committing updates to Public Git..."
git add -A
$DateStr = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
git commit -m "Run parse update on $DateStr" --allow-empty
git push origin main

Write-Host "Staging and committing updates to Private Git..."
$PrivateGitDir = Join-Path $PSScriptRoot ".private_git"
if (Test-Path $PrivateGitDir) {
    Remove-Item -Force "$PrivateGitDir\index.lock" -ErrorAction SilentlyContinue
    git --git-dir="$PrivateGitDir" --work-tree="$PSScriptRoot" add -A
    git --git-dir="$PrivateGitDir" --work-tree="$PSScriptRoot" add -f ":(exclude).venv/**" "**/*.als" "**/*.json" "**/*.png" "REPORT.md"

    git --git-dir="$PrivateGitDir" --work-tree="$PSScriptRoot" commit -m "Run private parse update on `$DateStr" --allow-empty
    git --git-dir="$PrivateGitDir" --work-tree="$PSScriptRoot" push origin main
}

Write-Host "Done!"
pause
