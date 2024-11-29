
$Host.UI.RawUI.WindowTitle = "ableton-parse-projects"
Set-Location "D:\Music Production\ableton projects"
python parse_projects.py | Tee-Object -FilePath "parse_projects.log"
pause