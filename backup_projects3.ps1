
$Host.UI.RawUI.WindowTitle = "ableton-backup"
# Invoke-Expression "C:\Python27\python.exe 'D:\Music Production\ableton projects\backup_projects.py'" | Tee-Object -FilePath "backup_projects.log"

Set-Location "D:\Music Production\ableton projects"

# python3 ##
python backup_projects3.py | Tee-Object -FilePath "backup_projects3.log"

pause