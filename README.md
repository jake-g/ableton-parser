# Ableton Project Parser

A Python tool that parses, analyzes and reports on Ableton Live project
files (`.als`).

## Features

- **Parsing** — reads `.als` files (gzip-compressed XML) and extracts
  tracks, devices, clips, tempo, key/scale and duration.
- **Samples** — resolves every sample reference: audio clips,
  Simpler/Sampler/Drum Rack devices, and samples referenced from inside
  plugin state. Records path, format, sample rate and duration.
- **Devices** — classifies each device as `instrument`, `effect` or
  `plugin`, and records the plugin binary path when present.
- **Plugin state** — best-effort recovery of readable strings from the
  opaque VST chunk: internal sample kits, library names, preset names and
  parameter labels.
- **Analysis** — 24 counters aggregated across all projects.
- **Reporting** — generates `REPORT.md` with plots (private remote only).
- **Logging** — console plus `outputs/parse_projects.log`.

---

## Quick Start

```bash
# 1. Create the venv and install dependencies
make setup

# 2. Parse projects and build the report
make run root="/path/to/Ableton/Projects"

# 3. Rebuild just the report from the cached parse
make report
```

---

## Makefile Commands

| Command | Description |
| :--- | :--- |
| `make help` | Lists every target (default target) |
| `make setup` | Creates `.venv` and installs dependencies |
| `make format` | Runs `pre-commit` linting and formatting |
| `make test` | Runs the unit test suite (`parse_projects_test.py`) |
| `make run` | Parses projects, then generates `REPORT.md` |
| `make report` | Regenerates `REPORT.md` from the cached parse |
| `make samples` | Summarizes `outputs/samples.tsv` (rows, sources, formats) |
| `make notebook` | Starts a Jupyter server configured for Colab |
| `make clean` | Removes generated outputs, logs and caches |
| `make verify-private` | Asserts the public/private boundary holds |
| `make private-status` | `git status` for the private data repo |
| `make private-add` | Stages data artifacts into the private repo |
| `make private-commit` | Commits data artifacts to the private repo |
| `make private-push` | Pushes the private repo to the Gitea remote |

### Run variables

| Variable | Default | Effect |
| :--- | :--- | :--- |
| `root` | `.` | Directory to scan for projects |
| `probe` | unset | Set to `1` to add `--probe-samples` |
| `midi` | unset | Set to `1` to add `--include-midi-clips` |
| `json` | `1` | Non-empty adds `--save-json`; set `json=` to disable |

```bash
make run root="/Users/me/Music/Ableton" probe=1 midi=1
make run json=        # skip per-project JSON sidecars
make samples          # inspect the sample table
```

---

## CLI Flags

`parse_projects.py` can also be run directly:

```bash
python parse_projects.py --root /path/to/projects --probe-samples
python generate_report.py
```

| Flag | Default | What it does |
| :--- | :--- | :--- |
| `--root PATH` | `.` | Root directory to search recursively for `.als` files |
| `--save-json` | off | Writes a self-contained `.json` next to each `.als` (same name, `.json` extension) |
| `--probe-samples` | off | Stats each sample on disk and reads WAV headers — fills `exists_on_disk`, `size_bytes`, `bit_depth`, `channels`. Required for the `samples_missing` counter |
| `--include-midi-clips` | off | Emits per-track MIDI clip details and the `midi_clip_is_loop` counter |
| `--debug` | off | Debug-level logging to the console |

> [!NOTE]
> `samples_missing` and `midi_clip_is_loop` stay empty unless
> `--probe-samples` / `--include-midi-clips` are passed. That is expected,
> not a bug.

---

## Counters (24)

Written to `outputs/counters.json` as `{counter: {value: count}}`.
**24 defined, 21 populated** in the latest run (455 projects, 0 errors,
65.2s). The three empty ones are expected: `samples_missing` needs
`--probe-samples`, `midi_clip_is_loop` needs `--include-midi-clips`, and
`warning_no_tracks` is empty because every project had tracks.

### Pre-existing (9)

| Counter | Question it answers |
| :--- | :--- |
| `ableton_version` | Which major Live version wrote each set? |
| `creation_year` | When were projects started? |
| `last_modified_year` | When were they last touched? |
| `track_types` | Audio vs MIDI vs return vs master mix |
| `device_types` | Which device tags appear most? |
| `plugins_vst` | Most-used VST plugins |
| `plugins_au` | Most-used Audio Unit plugins |
| `midi_clip_is_loop` | Are MIDI clips looped? (needs `--include-midi-clips`) |
| `warning_no_tracks` | How many sets parsed with zero tracks? |

### Added in 2.1.0 (15)

| Counter | Question it answers |
| :--- | :--- |
| `sample_files` | Which sample files are reused most? |
| `sample_extensions` | Format mix — wav / aif / mp3 / flac |
| `sample_sources` | Where samples come from: `audio_clip`, `device`, `plugin_kit` |
| `samples_missing` | Which references are broken on disk? (needs `--probe-samples`) |
| `warp_markers` | How heavily are audio clips warped? |
| `audio_clip_is_loop` | Loop vs one-shot balance for audio clips |
| `device_kinds` | Instrument / effect / plugin split |
| `instruments` | Which instruments (incl. Drum Racks) are used? |
| `effects` | Which audio effects are used? |
| `vst_libraries` | Which sample libraries do plugins pull from? (102 distinct) |
| `vst_strings` | Readable strings recovered from plugin state — preset names **and** parameter labels (1,631 distinct) |
| `au_presets` | AU preset names, as `Plugin: Preset` |
| `plugin_sample_files` | Individual sample filenames living inside plugins (2,413 distinct) |
| `plugin_sample_kits` | Kit folders referenced by plugins (178 distinct) |
| `plugins_with_samples` | Which plugins carry sample content at all? |

> [!NOTE]
> **`vst_strings` mixes presets with parameter labels.** The name
> accurately reflects what is recovered. Values are genuine readable strings
> pulled out of plugin binary state, but they fall into two groups: true preset
> names (`iZotope Ozone 5: Default`, `iZotope Alloy 2: Alloy 1`,
> `Maschine 2: Queensbridge Story`, `Reaktor 6 FX: Vocal Chords 1`) and
> plugin parameter labels (`Volume`, `Threshold`, `Attack`, `Side-Chain`).
> Treat it as "readable plugin strings", not a clean preset inventory.
> An earlier version of this counter was ~95% binary noise; the hardened
> filter cut it from 2,242 to 1,631 distinct values and the remainder is
> legitimate.

---

## Per-Project JSON Fields

Emitted with `--save-json`, and mirrored in the in-memory record.

| Field | Meaning |
| :--- | :--- |
| `samples[]` | Flat list of every sample reference in the set |
| `num_samples` | Total sample references |
| `num_unique_samples` | Distinct sample filenames |
| `num_audio_clips` | Audio clip count |
| `num_midi_clips` | MIDI clip count |
| `tracks[].devices[].kind` | `instrument` / `effect` / `plugin` |
| `tracks[].devices[].plugin_path` | On-disk plugin binary path |
| `tracks[].devices[].vst_preset` | Recovered plugin state (below) |

Alongside the pre-existing `path`, `name`, `ableton_version_full`,
`file_size_mb`, `created`, `modified`, `num_tracks`, `tempo`,
`time_signature`, `scale_root`, `scale_name`, `duration_sec`, `tracks[]`
and `counters`.

### The `vst_preset` block

| Field | Meaning |
| :--- | :--- |
| `byte_size` | Size of the decoded plugin chunk |
| `sample_count` | Total internal sample paths found |
| `sample_kits[]` | `{path, count, samples[]}` grouped by folder |
| `libraries[]` | e.g. `Maschine 2 Factory Library` |
| `preset_names[]` | Preset names and parameter labels (see counter note) |
| `sample_paths[]` | Raw paths, **opt-in** via `as_dict(full_paths=True)` |

Kits are capped at 32 folders with 32 filenames each; name lists are
capped at 50 entries.

### Why plugin samples are logged per kit folder

A single plugin kit typically references dozens of samples that all live
under one directory, so one row per file just repeats the same prefix over
and over. Plugin-internal samples are therefore recorded **per kit folder**
rather than per file: **6,375 per-file rows collapsed to 1,198 kit rows**
across 178 distinct kit folders, cutting the sample table from **31,880 to
26,703 rows (−16%)**.

No detail is lost:

- every filename is still counted in the `plugin_sample_files` counter
  (2,413 distinct names),
- each kit row carries `sample_count` plus a `sample_names` list of the
  filenames in that folder,
- extensions are still counted per file into `sample_extensions`.

Samples found in audio clips and in Simpler/Sampler/Drum Rack devices are
unaffected — those remain one row per reference.

---

## Sample Output

### Per-project JSON (trimmed)

```json
{
  "name": "fate beat 12 Project",
  "num_samples": 42,
  "num_unique_samples": 31,
  "num_audio_clips": 12,
  "num_midi_clips": 8,
  "samples": [
    {
      "name": "kick_01.wav",
      "path": "B:/Music Production/Samples/kick_01.wav",
      "relative_path": "Samples/Imported/kick_01.wav",
      "extension": ".wav",
      "source": "audio_clip",
      "sample_rate": 44100,
      "duration_sec": 1.204,
      "exists_on_disk": true,
      "bit_depth": 24,
      "channels": 2,
      "size_bytes": 318604,
      "track_index": 3,
      "clip_name": "kick loop"
    }
  ],
  "tracks": [
    {
      "index": 1,
      "type": "MidiTrack",
      "devices": [
        {
          "type": "PluginDevice",
          "preset": "Maschine 2",
          "kind": "plugin",
          "plugin_path": "C:/Program Files/VstPlugins/Maschine 2.dll",
          "vst_preset": {
            "byte_size": 184320,
            "sample_count": 64,
            "sample_kits": [
              {
                "path": "C:/Maschine 2 Library/Drums/Kick",
                "count": 12,
                "samples": ["Kick AR60sLate V98 1.wav", "..."]
              }
            ],
            "libraries": ["Maschine 2 Factory Library"],
            "preset_names": ["Default"]
          }
        }
      ]
    }
  ]
}
```

### `outputs/samples.tsv`

One row per sample reference (kit rows for plugin samples):

| Column | Notes |
| :--- | :--- |
| `name` | Filename, or the kit folder name for `plugin_kit` rows |
| `path` | Absolute path as stored in the set |
| `relative_path` | Path relative to the project folder |
| `extension` | Lowercased, with the dot |
| `source` | `audio_clip` · `device` · `plugin_kit` |
| `sample_rate` | From the set, or the WAV header when probed |
| `duration_sec` | Derived from duration / sample rate |
| `exists_on_disk` | Only populated with `--probe-samples` |
| `bit_depth` | WAV only, `--probe-samples` |
| `channels` | WAV only, `--probe-samples` |
| `size_bytes` | `--probe-samples` |
| `track_index` | 1-based track index |
| `clip_name` | Clip name, or device name for device samples |
| `plugin` | Plugin name — `plugin_kit` rows only |
| `sample_count` | Files in the kit — `plugin_kit` rows only |
| `sample_names` | `\|`-joined filenames — `plugin_kit` rows only |
| `project` | Project name |
| `project_path` | Path to the `.als` file |

```tsv
name	path	extension	source	duration_sec	track_index	plugin	project
kick_01.wav	B:/.../kick_01.wav	.wav	audio_clip	1.204	3		fate beat 12
vox chop.aif	B:/.../vox chop.aif	.aif	device	0.517	5		fate beat 12
Kick	C:/Maschine 2 Library/Drums/Kick		plugin_kit		1	Maschine 2	fate beat 12
```

---

## Project Layout

```
.
├── Makefile                # Unified cross-platform commands (recommended)
├── parse_projects.py       # Core XML parsing engine for .als files
├── generate_report.py      # Aggregation and markdown report generator
├── parse_projects_test.py  # Unit tests
├── requirements.txt        # Python dependencies
├── run_parse.ps1           # Scheduled-run wrapper for the Windows host
├── REPORT.md               # Detailed stats (private remote only)
└── outputs/                # Generated directory (private remote only)
    ├── projects.tsv        # One row per project
    ├── samples.tsv         # One row per sample reference
    ├── counters.json       # Aggregated counters
    ├── project_info.pkl    # Parse cache used by `make report`
    ├── parse_projects.log  # Run log
    └── plots/              # Charts (version, tempo, plugins, samples…)
```

### Example target project structure (never committed)

The parser recursively scans your project folders. Project folders, audio
files and local samples are excluded by `.gitignore`:

```
My Music/
└── Projects/
    ├── Project A/
    │   ├── Project A.als       # Ableton Live Set (gzipped XML)
    │   ├── Project A.cfg       # Config (optional)
    │   └── Samples/            # Audio samples (skipped and ignored)
    ├── Project B/
    │   ├── Project B v1.als
    │   └── Project B v2.als
    └── ...
```

Directories named `Backup`, `old`, `Samples`, `Ableton Project Info`,
`z__templates`, `outputs`, `.git`, `.stfolder`, `.stversions` and
`.ipynb_checkpoints` are skipped. Matching is on **whole path components**,
so a folder named `Gold` or `folder` is no longer mistaken for `old`.

---

## Privacy Model — Two Remotes, One Working Tree

> [!IMPORTANT]
> This is a hard requirement, not a preference. The public remote carries
> **code and config only**.

| Remote | Git dir | Carries |
| :--- | :--- | :--- |
| Public GitHub (`origin`) | `.git` | Code and config — 10 files, nothing else |
| Private Gitea | `.private_git` | Everything: reports, outputs, media, notebooks |

The public remote tracks exactly these 10 files:

```
.github/workflows/ci.yml   .gitignore   .pre-commit-config.yaml
Makefile   README.md   requirements.txt
generate_report.py   parse_projects.py   parse_projects_test.py
run_parse.ps1
```

**Never allowed on the public remote:**

- `REPORT.md` and any generated report
- `outputs/` — `counters.json`, `projects.tsv`, `samples.tsv`, logs, plots
- media — `*.als`, `*.wav`, `*.aif(f)`, `*.mp3`, `*.flac`, `*.m4a`, `*.asd`
- notebooks — `*.ipynb`
- any `*.tsv` or `*.pkl`
- planning files — `TODO*`, `PLAN*`

Run the guard before every public push:

```bash
make verify-private
```

It fails loudly if any of the above is tracked by, or would be staged
into, the public repo. Private artifacts go out with `make private-push`.

> [!NOTE]
> Public GitHub **history** has been purged of private files that were
> committed before the boundary was enforced (`REPORT.md`,
> `ableton_projects.ipynb`, `projects.tsv`, `outputs/`, `*.log`) using
> `git filter-repo`. Verified afterwards: tip tree hash byte-identical,
> 46 → 37 commits, zero private blobs reachable.

---

## Development

- **Style** — Google Python Style: 2-space indent, 80 columns, typed
  signatures, Google-style docstrings, `logging` (never `print`).
- **Formatting** — `make format` runs pre-commit over all files.
- **Testing** — `make test`; **32 tests** covering sample extraction,
  sample-kit grouping, preset-name filtering, skip-dir matching, error
  reporting and VST chunk parsing.

---

## Changelog

### [2.1.0] - 2026-09-20 (Samples & Plugin State)

#### Added
- **Sample extraction** — three paths (audio clips, Simpler/Sampler/Drum
  Rack devices, plugin-internal state) recovering **31,880 references,
  up from 0**. New `outputs/samples.tsv` (26,703 × 18 after kit
  grouping); `projects.tsv` is 455 × 36.
- **VST/AU preset extraction** — readable strings recovered from the
  opaque plugin chunk: internal sample paths, library names, AU preset
  names, plus preset names and parameter labels.
- **Kit-based plugin sample logging** — plugin samples are recorded per
  kit folder, collapsing 6,375 rows to 1,198 and the whole sample table
  from 31,880 to **26,703 rows (−16%)** with no loss of detail.
- **New CLI flags** — `--probe-samples`, `--include-midi-clips`,
  `--save-json`.
- **New Makefile targets** — `samples`, `verify-private`, plus the
  `private-*` family; `clean` now removes `samples.tsv`.
- **15 new counters**, taking the total from 9 to **24** (21 populated).

#### Fixed
- **`should_skip_dir` matched substrings** — `'old'` matched `'folder'`,
  silently dropping projects. Now matches whole path components;
  **2 projects recovered** (453 → 455).
- **Error count was always 0** — a bare `except: pass` hid every parse
  failure. Errors are now counted, listed and logged.
- **`LiveSetAudioClipData` was a stub** — no audio clip or warp data was
  produced at all; now fully implemented.
- **Plugin samples skipped `sample_extensions`** — the format mix was
  undercounted.
- **Preset-name extraction was ~95% binary noise** — a hardened filter
  now rejects byte-reversed chunk IDs (`'atad` from `data`), magic
  markers with stray trailing bytes (`DSINe`, `ofnibilzD`), GUIDs,
  embedded config fragments (`midiMap = {`) and long encoded patch-data
  runs (Zebra2). `vst_strings` (formerly `vst_presets`) went from 2,242
  mostly-garbage values to **1,631 legitimate ones**, and is now included in
  `REPORT.md`.

#### Changed
- **Tests: 1 → 32**, adding `TestPresetNameFilter` and
  `TestSampleKitGrouping` alongside sample extraction, skip-dir matching,
  error reporting and VST chunk parsing.
- `vst_preset` serializes kit folders instead of every raw path; raw paths
  are opt-in via `full_paths=True`.

### [2.0.1] - 2026-05-06 (Public Release Preparation)
#### Added
- **Cross-Platform Makefile**: unified targets (`setup`, `run`, `test`,
  `format`, `notebook`, `zip-skeleton`, `clean`).
- **`REPORT.md`**: standalone file for detailed analysis, decoupling stats
  and file listings from the public `README.md`.

### [2.0.0] - 2026-02-23 (Refactor Release)
#### Added
- **Classes**: `ALSNode`, `LiveSetData`, `LiveSetTrackData`,
  `LiveSetDeviceData` for modular XML parsing.
- **Reporting**: `generate_report.py`
    - Summary statistics and plots written into `REPORT.md`.
    - Plots for Ableton versions, creation year, last modified year, track
      types, device types, top plugins (VST/AU), tempo distribution, file
      size, tracks per project.
    - Comprehensive project inventory table (including scale, duration).
- **Extraction**: tempo, time signature, key/scale and project duration.
- **Logging**: `logging` module, file + console.
- **Testing**: `parse_projects_test.py` with `unittest` and mock XML.
- **Config**: `requirements.txt` and `.pre-commit-config.yaml`.
- **Scripts**: `run_parse.sh` and `run_parse.ps1`.

#### Changed
- **Output**: relocated to `outputs/` to keep the root clean.
- **Cache**: replaced timestamped pickles with a single `project_info.pkl`.
- **JSON**: per-project `.json` output disabled by default.
- **Refactor**: rewrote `parse_projects.py` to Google Python Style.

### [1.2] - 2025-12-10
#### Added
- Support for the Ableton 11 XML structure.
- Extraction of VST/AU plugin names.

### [1.1] - 2025-08-15
#### Added
- Basic TSV export (`projects.tsv`).
- Extraction of tempo and time signature.

### [1.0] - 2025-01-01
#### Initial Release
- Basic parsing of `.als` files (gzipped XML).
- Extraction of track count and file size.
- Simple print debugging.
