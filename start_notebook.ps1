$Host.UI.RawUI.WindowTitle = "ableton-parse-server"
Set-Location "D:\Music Production\ableton projects"
pip3 install jupyter ipykernel pandas matplotlib numpy --upgrade
$mypath = Split-Path -Parent $MyInvocation.MyCommand.Path
jupyter notebook --NotebookApp.allow_origin='https://colab.research.google.com' --port=8887 --NotebookApp.port_retries=0