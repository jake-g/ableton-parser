# Ableton Project Parser

A Python-based tool to parse, analyze, and report on Ableton Live project files (`.als`).

## Features
- **Parsing**: Extracts detailed information from `.als` files (gzip-compressed XML).
- **Analysis**: Aggregates statistics on tracks, devices, plugins, and tempo.
- **Reporting**: Generates a Markdown report (`outputs/REPORT.md`) with visualizations.
- **Logging**: Detailed logging to console and file (`outputs/parse_projects.log`).

## Setup

### Prerequisites
- Python 3.8+
- [Optional] Virtual environment recommended.

### Installation
1.  Clone or download this repository.
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## Usage

### macOS / Linux
Run the wrapper script:
```bash
./run_parse.sh
```
Or run manually:
```bash
python parse_projects.py --root /path/to/projects
python generate_report.py
```

### Windows
Run the PowerShell script:
```powershell
.\run_parse.ps1
```

## Directory Structure

```
.
├── parse_projects.py       # Main parsing logic
├── generate_report.py      # Report generation
├── outputs/                # Generated outputs
│   ├── REPORT.md           # Summary report
│   ├── projects.tsv        # Project data in TSV format
│   ├── counters.json       # Aggregated statistics
│   └── plots/              # generated charts
├── requirements.txt        # Python dependencies
└── run_parse.sh            # Runner script

# Example Project Structure
My Music/
├── Projects/
│   ├── Project A/
│   │   ├── Project A.als       # Ableton Live Set
│   │   ├── Project A.cfg       # Config (optional)
│   │   └── Samples/            # Audio samples
│   ├── Project B/
│   │   ├── Project B v1.als
│   │   └── Project B v2.als
│   └── ...
```

## Development
- **Style**: Google Python Style (2 spaces).
- **Pre-commit**: Run `pre-commit run --all-files` to format code.
- **Tests**: Run `python parse_projects_test.py`.

<!-- REPORT_START -->
**Generated:** 2026-02-23 22:52:12.426826

### Overview
- **Total Projects:** 451
- **Total Size:** 104.37 MB
- **Date Range:** 2026-02-23 20:10:50 to 2026-02-23 20:10:50

### Potential Compatibility Issues
### Deprecated Plugins Check
No deprecated plugins found.

### Audio Unit (AU) Compatibility Check
> These projects use Audio Units instead of VSTs, which may not load on Windows.
- **Crystallizer** found in: 3-32, 3-8

### Top Plugins
#### VST

| Plugin           |   Count |
|:-----------------|--------:|
| Guitar Rig 5     |     358 |
| iZotope Ozone 5  |     211 |
| Maschine 2       |     166 |
| Komplete Kontrol |     134 |
| Solid Bus Comp   |      41 |
| Toraverb         |      29 |
|                  |      26 |
| Reaktor 6 FX     |      25 |
| Tal-Chorus-LX    |      21 |
| iZotope Alloy 2  |      17 |
| TAL-Chorus-LX    |      17 |
| Guitar Rig 6     |      11 |
| GS-201           |      10 |
| Zebra2           |       6 |
| Dirt             |       5 |
| ValhallaRoom     |       5 |
| Drumazon         |       5 |
| Driver           |       4 |
| Toraverb2        |       3 |
| LuSH-101         |       2 |

#### AU

| Plugin       |   Count |
|:-------------|--------:|
| GS-201       |      36 |
| Crystallizer |       2 |

### Project Inventory (Top 50 Recently Modified)
| name                                     |   ableton_version_full |    tempo | scale_root   | scale_name   |   duration_sec |   num_tracks |   file_size_mb | modified            |
|------------------------------------------|------------------------|----------|--------------|--------------|----------------|--------------|----------------|---------------------|
| unsorted loops                           |                12.0121 |  78      | nan          | 0            |           0    |            8 |           0.14 | 2025-12-12 22:26:20 |
| chill guitar beats lekato                |                12.0121 |  75      | nan          | 0            |        1598.4  |           32 |           1.49 | 2025-12-12 19:47:50 |
| Untitle3d                                |                11.0113 |  70      | C            | Major        |           0    |           10 |           0.01 | 2025-08-10 00:57:08 |
| lekato drums template                    |                11.0113 |  70      | C            | Major        |           0    |           10 |           0.06 | 2025-08-09 21:32:12 |
| Untitled2                                |                11.0113 |  70      | C            | Major        |           0    |           10 |           0.01 | 2025-08-03 23:34:56 |
| acoustic digi                            |                11.0113 |  60      | C            | Major        |         285.74 |            6 |           0.03 | 2025-07-31 23:52:04 |
| dimensions and space 24                  |                11.0113 |  66      | C            | Major        |        1554.09 |            8 |           0.04 | 2025-07-01 21:38:36 |
| 1                                        |                11.0113 |  67      | C            | Major        |         186.27 |           28 |           1.41 | 2025-06-28 20:08:34 |
| 2                                        |                11.0113 |  89      | C            | Major        |         164.6  |           21 |           1.15 | 2025-06-28 19:52:20 |
| portasynth 25                            |                11.0113 |  65      | C            | Major        |           0    |            7 |           0.19 | 2025-06-28 18:40:16 |
| lounge jam                               |                11.0113 |  70.1534 | C            | Major        |         102.63 |            5 |           0.01 | 2025-04-27 02:55:38 |
| long                                     |                11.0113 |  60      | C            | Major        |           0    |            7 |           0.17 | 2025-04-07 21:06:10 |
| simp synth                               |                12.0121 |  72.7883 | nan          | 0            |           0    |            5 |           0.03 | 2025-03-24 21:05:54 |
| slide dist exp                           |                11.0113 |  80      | C            | Major        |           0    |            6 |           0.14 | 2025-02-08 22:02:24 |
| caiaso 32 jarry braz                     |                11.0113 |  76      | C            | Major        |         480    |            7 |           0.15 | 2025-02-08 21:59:42 |
| _casio cheez demos                       |                11.0113 | 120      | C            | Major        |        3290.48 |           26 |           0.38 | 2025-02-08 21:58:18 |
| trasncriptoi to midi                     |                11.0113 | 154.513  | C            | Major        |           0    |            8 |           0.95 | 2025-02-08 21:50:24 |
| broken fluit fly                         |                11.0113 |  63      | C            | Major        |         402.38 |           14 |           0.27 | 2025-02-08 21:48:50 |
| cas wonk synth revsdn                    |                11.0113 |  75      | C            | Major        |         338    |            2 |           0.02 | 2025-02-08 21:47:50 |
| summa time                               |                12.0121 |  67      | nan          | 0            |           0    |           13 |           0.09 | 2025-02-08 14:23:50 |
| chior                                    |                11.0113 |  77      | C            | Major        |          87.35 |           10 |           0.12 | 2025-01-17 13:46:32 |
| jah chopped                              |                11.0113 | 100.136  | C            | Major        |           0    |            2 |           0.03 | 2024-12-28 13:01:14 |
| nylonoer                                 |                11.0113 |  73.8281 | C            | Major        |         331.02 |            5 |           0.18 | 2024-12-12 01:35:32 |
| witch mixdown                            |                10.0377 | 118      | C            | Major        |         140.34 |           13 |           0.44 | 2024-12-06 21:22:16 |
| gitin it all bad [beat][witch] [loops] 2 |                10.0377 |  65.4596 | C            | Major        |         117.32 |           10 |           0.4  | 2024-12-06 21:19:30 |
| lofi accoustic psych                     |                10.0377 |  75      | C            | Major        |         172.8  |            8 |           0.1  | 2024-12-06 21:18:08 |
| psych guiTarr beat                       |                10.0377 |  91.0734 | C            | Major        |         155.71 |            7 |           0.19 | 2024-12-06 21:15:26 |
| _guitar pop beats_mixed                  |                11.0113 |  73      | C            | Major        |         449.18 |            5 |           0.01 | 2024-12-06 21:13:04 |
| pavemennt gsi                            |                10.0377 |  79.0954 | C            | Major        |         133.97 |            5 |           0.03 | 2024-12-06 21:10:46 |
| sad jammm living romom                   |                10.0377 |  73      | C            | Major        |         158.46 |            4 |           0.06 | 2024-12-06 21:09:30 |
| bitcrush distortion jam 303              |                10.0377 |  59      | C            | Major        |         414.84 |            2 |           0.01 | 2024-12-06 21:08:20 |
| 6 + 7 Project                            |                10.0377 |  89.1781 | C            | Major        |         189.94 |           36 |           1.56 | 2024-12-06 21:04:12 |
| mello loops upmix                        |                10.0377 | 120      | C            | Major        |          70    |            8 |           0.22 | 2024-12-06 21:01:50 |
| jd jazzy wonk bet                        |                10.0377 |  73      | C            | Major        |         322.19 |            5 |           0.09 | 2024-12-06 20:54:20 |
| _machine beats                           |                10.0377 |  68      | C            | Major        |         409.41 |            5 |           0.17 | 2024-12-06 20:51:44 |
| trum kahled 10                           |                10.0377 |  70      | C            | Major        |         281.1  |           14 |           3.38 | 2024-12-06 20:50:30 |
| jarryork                                 |                11.0113 |  78      | C            | Major        |         221.54 |            6 |           0.09 | 2024-12-03 00:10:06 |
| jarryork 23                              |                11.0113 |  78      | C            | Major        |         221.54 |            5 |           0.09 | 2024-12-03 00:05:14 |
| loose acousitc distorted vox loop jam    |                11.0113 |  62      | C            | Major        |         735.48 |            7 |           0.2  | 2024-12-02 23:59:50 |
| kyle Jake funk [house][loops]            |                10.0377 | 112      | C            | Major        |           0    |           11 |           0.18 | 2024-12-02 22:45:34 |
| room floor dual acoustics am-g-bm 3.5    |                11.0113 |  80      | C            | Major        |         203.74 |            5 |           0.03 | 2024-12-02 22:43:48 |
| organic odwala faster 10                 |                10.0377 | 108      | C            | Major        |         222.22 |           24 |           0.29 | 2024-12-02 22:43:00 |
| _witchr                                  |                11.0113 |  63      | C            | Major        |         329.66 |            2 |           0.01 | 2024-12-02 22:40:54 |
| death flutes a10                         |                10.0377 |  78      | C            | Major        |         320    |            8 |           0.34 | 2024-12-02 22:40:12 |
| soul hiphoppy guitar                     |                10.0377 |  85.1863 | C            | Major        |           0    |            8 |           0.14 | 2024-12-02 22:37:16 |
| funky smoov                              |                11.0113 |  88      | C            | Major        |          54.55 |            6 |           0.16 | 2024-12-02 22:34:08 |
| chill guitar track                       |                11.0113 |  62.9281 | C            | Major        |         335.62 |            9 |           0.79 | 2024-12-02 22:32:58 |
| acoustic sad vox                         |                11.0113 | 134      | C            | Major        |         143.28 |            6 |           0.03 | 2024-12-02 22:31:32 |
| drum track improv 10                     |                10.0377 |  62.9281 | C            | Major        |           0    |            9 |           0.11 | 2024-12-02 22:30:28 |
| burn it to the ground                    |                11.0113 | 105      | C            | Major        |           0    |            7 |           0.04 | 2024-12-02 22:28:54 |

### Graphs
#### Ableton Version
![ableton_version](outputs/plots/ableton_version.png)

#### Creation Year
![creation_year](outputs/plots/creation_year.png)

#### Last Modified Year
![last_modified_year](outputs/plots/last_modified_year.png)

#### Track Types
![tracks_dist](outputs/plots/tracks_dist.png)

#### Device Types (Top 20)
![device_types](outputs/plots/device_types.png)

#### File Size
![filesize_dist](outputs/plots/filesize_dist.png)

#### Tempo Distribution
![tempo](outputs/plots/tempo_dist.png)

#### Top VSTs
![top_vst](outputs/plots/top_vst.png)

#### Top AUs
![top_au](outputs/plots/top_au.png)

<!-- REPORT_END -->

## Changelog

All notable changes to this project will be documented in this section.

### [2.0.0] - 2026-02-23 (Refactor Release)
#### Added
- **Classes**: Introduced `ALSNode`, `LiveSetData`, `LiveSetTrackData`, `LiveSetDeviceData` for modular XML parsing.
- **Reporting**: Added `generate_report.py`
    - Injects summary statistics and plots directly into `README.md`.
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
