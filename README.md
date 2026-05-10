# Ableton Project Parser

A Python-based tool to parse, analyze, and report on Ableton Live project files (`.als`).

## Features
- **Parsing**: Extracts detailed information from `.als` files (gzip-compressed XML).
- **Analysis**: Aggregates statistics on tracks, devices, plugins, and tempo.
- **Reporting**: Generates a Markdown report (`REPORT.md`) with visualizations.
- **Logging**: Detailed logging to console and file (`outputs/parse_projects.log`).

### Quick Start
1. Set up your virtual environment and install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
2. Run a full parse:
    ```bash
    make run
    ```
3. Generate a report:
    ```bash
    make report
    ```

### All Makefile Commands
| Command | Description |
| :--- | :--- |
| `make setup` | Creates a Python virtual environment (`.venv`) and installs all dependencies |
| `make format` | Runs `pre-commit` formatting and styling checks to keep code pristine |
| `make test` | Executes the Python unit test suite (`parse_projects_test.py`) |
| `make run` | Parses your Ableton projects and generates a detailed report (`REPORT.md`) |
| `make report` | Regenerates the `REPORT.md` from cached parsing data without rescanning files |
| `make notebook` | Starts a local Jupyter Notebook server pre-configured for Google Colab integration |
| `make clean` | Deletes generated outputs, temporary logs, and caches to reset the workspace |

### Customizing the Search Directory
By default, `make run` searches the current directory for Ableton projects. To target a specific folder, pass the `root` variable:
```bash
make run root="/Users/username/Music/Ableton/Projects"
```

#### Running Manually
```bash
# 1. Run the parser (searches current directory by default, use --root to search a custom path)
python parse_projects.py --root /path/to/projects

# 2. Generate the report (creates REPORT.md)
python generate_report.py
```

---

## Project Layout

```
.
├── Makefile                # Unified cross-platform commands (recommended)
├── parse_projects.py       # Core XML parsing engine for .als files
├── generate_report.py      # Aggregation and markdown report generator
├── REPORT.md               # Detailed personal stats, plugins list, and inventory
├── parse_projects_test.py  # Unit tests
├── requirements.txt        # Python dependencies
└── outputs/                # Generated directory
    ├── projects.tsv        # Flat database of all project parameters
    ├── counters.json       # Aggregated count statistics
    └── plots/              # Statistical charts (version, tempo, plugins, etc.)
```

## Repository Structure
This repository uses a two-branch system to separate public code from personal data:
- **`main` (Public)**: The primary branch for the parser code, documentation, and tooling. It does **not** include any personal project folders or data.
- **`dev` (Private)**: A private branch (typically backed up to a personal remote) that includes the parser code along with your actual Ableton project folders.

> [!IMPORTANT]
> When contributing or pushing to a public remote (like GitHub), ensure you are on the `main` branch to avoid accidentally sharing private project metadata or folders.

### Example Target Project Structure
The parser recursively scans your project folders (such as `My Music/` below). All actual project folders, audio files, and local samples are fully ignored by `.gitignore` to protect your privacy:
```
My Music/
└── Projects/
    ├── Project A/
    │   ├── Project A.als       # Ableton Live Set (zipped XML metadata)
    │   ├── Project A.cfg       # Config (optional)
    │   └── Samples/            # Audio samples (automatically ignored)
    ├── Project B/
    │   ├── Project B v1.als
    │   └── Project B v2.als
    └── ...
```

---

## Development
- **Style Guide**: Internal Google Python Style (2-space indentation, rigorous type annotations).
- **Pre-commit Validation**: `make format` enforces strict linting and formatting.
- **Testing**: `make test` verifies parser node extraction integrity.


## Changelog

All notable changes to this project will be documented in this section.

### [2.0.1] - 2026-05-06 (Public Release Preparation)
#### Added
- **Cross-Platform Makefile**: Introduced a unified `Makefile` supporting standard automation command targets (`setup`, `run`, `test`, `format`, `notebook`, `zip-skeleton`, `clean`).
- **`REPORT.md`**: Created a standalone root file for detailed analysis, decoupling all sensitive stats and file listings from the public `README.md`.

### [2.0.0] - 2026-02-23 (Refactor Release)
#### Added
- **Classes**: Introduced `ALSNode`, `LiveSetData`, `LiveSetTrackData`, `LiveSetDeviceData` for modular XML parsing.
- **Reporting**: Added `generate_report.py`
    - Generates summary statistics and plots directly into `REPORT.md`.
    - Generate plots for:
        - Ableton versions, Creation year, Last modified year
        - Track types, Device types, Top Plugins (VST/AU)
        - Tempo Distribution, File Size, Tracks per Project
    - Comprehensive Project Inventory table (including Scale, Duration).
- **Extraction**:
    - **Tempo**, **Time Signature**, **Key/Scale**, and **Project Duration** from `.als` files.
- **Logging**: Implemented robust logging using Python's `logging` module (file + console).
- **Testing**: Added `parse_projects_test.py` with `unittest` and mock XML data.
- **Config**: Added `requirements.txt` and `.pre-commit-config.yaml` for dependency and style management.
- **Scripts**: Added `run_parse.sh` and `run_parse.ps1` for easy execution.

#### Changed
- **Output**: Relocated all outputs to `outputs/` directory to keep root clean.
- **Cache**: Replaced timestamped pickle files with a single `project_info.pkl`.
- **JSON**: Disabled default generation of per-project `.json` files to reduce clutter.
- **Refactor**: Rewrote `parse_projects.py` to adhere to Google Python Style Guide (2-space indent, typed).

### [1.2] - 2025-12-10
#### Added
- Added support for Ableton 11 XML structure.
- Added extraction of VST/AU plugin names.

### [1.1] - 2025-08-15
#### Added
- Basic CSV export functionality (`projects.tsv`).
- Added extraction of tempo and time signature.

### [1.0] - 2025-01-01
#### Initial Release
- Basic parsing of `.als` files (gzipped XML).
- Extraction of track count and file size.
- Simple print debugging.
