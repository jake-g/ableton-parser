
#!/bin/bash
set -e

VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment in $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

python3 -m pip install --upgrade pip jupyterlab pandas matplotlib scipy numpy
echo https://colab.research.google.com/drive/1mvMnzVS_41HieqnTvfK1vzESBkqOVSvv
jupyter notebook \
  --NotebookApp.allow_origin='https://colab.research.google.com' \
  --port=8887 \
  --NotebookApp.port_retries=0

