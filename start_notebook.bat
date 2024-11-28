pip install jupyter ipykernel jupyter_http_over_ws pandas matplotlib numpy --upgrade
call jupyter serverextension enable --py jupyter_http_over_ws
SET mypath=%~dp0
echo %mypath:~0,-1%
call jupyter notebook --NotebookApp.allow_origin='https://colab.research.google.com' --port=8887 --NotebookApp.port_retries=0
