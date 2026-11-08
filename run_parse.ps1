# Set strict error handling
param(
    [switch]$UpgradeDeps,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ParserArgs
)

$ErrorActionPreference = "Stop"

$Host.UI.RawUI.WindowTitle = "ableton-project-parser"
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

# Assume python is available in path or .venv already active/available
$Python = "python"
Write-Host "Using Python: $Python"

$PipStamp = "logs\last_pip_upgrade.txt"
if ($UpgradeDeps -or -not (Test-Path $PipStamp) -or ((Get-Date) - (Get-Item $PipStamp).LastWriteTime).TotalDays -ge 30) {
    Write-Host "Updating requirements..."
    & $Python -m pip install --upgrade -r requirements.txt
    if ($LASTEXITCODE -eq 0) { Get-Date -Format "o" | Set-Content -Path $PipStamp -Encoding UTF8 }
}

Write-Host "Running pre-commit..."
& $Python -m pre_commit run --all-files

Write-Host "Running tests..."
& $Python parse_projects_test.py

Write-Host "Running parser..."
# Use Tee-Object to capture log while showing output, mirroring user's preference
& $Python parse_projects.py --save-json @ParserArgs | Tee-Object -FilePath "outputs/parse_projects.log"

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
    git --git-dir="$PrivateGitDir" --work-tree="$PSScriptRoot" add -f "**/*.als" "**/*.json" "**/*.png" "REPORT.md"

    git --git-dir="$PrivateGitDir" --work-tree="$PSScriptRoot" commit -m "Run private parse update on $DateStr" --allow-empty
    git --git-dir="$PrivateGitDir" --work-tree="$PSScriptRoot" push origin main
}

Write-Host "Done!"
pause
