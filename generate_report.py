"""Builds REPORT.md and its supporting plots from parsed project data.

The report stays generic: it describes counts, distributions and
aggregate findings, never gear-specific or workflow-specific advice.
"""

import logging
import os
import pickle
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
import warnings

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from parse_projects import save_counters

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Suppress noisy library logs
logging.getLogger('matplotlib').setLevel(logging.WARNING)
logging.getLogger('seaborn').setLevel(logging.WARNING)
# Suppress matplotlib warnings about categorical units
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
warnings.filterwarnings("ignore", category=FutureWarning, module="seaborn")

# Configuration
CACHE_FILE = 'outputs/project_info.pkl'
OUTPUT_DIR = 'outputs'
PLOTS_DIR = os.path.join(OUTPUT_DIR, 'plots')

# Set Academic Style
sns.set_theme(style="whitegrid", context="paper", font_scale=1.2)
# Use a colorblind-friendly palette
PALETTE = "viridis"

# Counters that must never reach the report.
#
# Kept as an explicit, greppable guard rather than relying on a counter
# simply never being referenced. `counter_series` consults this set, so
# adding a name here removes its section and its plot in one edit.
#
# History: `vst_strings` (formerly `vst_presets`) was blocked here while
# its extraction was ~95% binary noise (byte-reversed magic IDs, GUIDs,
# Lua fragments). The name filter has since been hardened and re-verified
# against real data, so it is reported again - with the accuracy caveat
# in `VST_STRINGS_CAVEAT`.
EXCLUDED_COUNTERS: frozenset[str] = frozenset()

# `vst_strings` holds readable strings scraped from opaque plugin state.
# They are genuine strings, but they are a mix of true preset names and
# plugin parameter labels, so the report must not present them as a
# clean preset list.
VST_STRINGS_CAVEAT = (
    "> These are readable strings recovered from plugin state: a mix of "
    "true preset names (e.g. a saved patch) and plugin parameter labels "
    "(e.g. a knob name). Both are genuine, but this is not a clean list "
    "of presets - read each row as \"a string the plugin stored\", not "
    "\"a preset the user chose\".\n")


# Longest category label rendered on a plot axis or in a table before it
# gets elided in the middle.
MAX_LABEL_LEN = 40
MAX_TABLE_LABEL_LEN = 60

# Lossy formats, used for the format-mix narrative.
LOSSY_EXTENSIONS = frozenset({'.mp3', '.m4a', '.aac', '.ogg', '.wma'})

# Sample sources that an audio-clip-only extractor would never see.
NON_CLIP_SOURCES = ('device', 'plugin_kit')


def generate_markdown_table(data: Any,
                            headers: Optional[List[str]] = None) -> str:
  """Generate a markdown table from a DataFrame or Series.

  Args:
    data: A pandas Series, DataFrame, or any object with `to_markdown`.
    headers: Optional column headers for the rendered table.

  Returns:
    The table as a github-flavoured markdown string.
  """
  if isinstance(data, pd.Series):
    name = headers[1] if headers and len(headers) > 1 else 'Count'
    data = data.to_frame(name=name)

  if headers and isinstance(data, pd.DataFrame):
    # If headers provided, we might need to handle index resetting
    # outside or here. But basic usage:
    return data.to_markdown(headers=headers, tablefmt="github")

  if hasattr(data, 'to_markdown'):
    return data.to_markdown(tablefmt="github")

  return str(data)


def load_data(cache_file: str) -> Dict[str, Any]:
  """Load project data from pickle.

  Args:
    cache_file: Path to the pickled parse results.

  Returns:
    The parsed project mapping, or an empty dict when unavailable.
  """
  if not os.path.exists(cache_file):
    logger.error("Cache file %s not found.", cache_file)
    return {}
  with open(cache_file, 'rb') as f:
    return pickle.load(f)


def truncate_label(label: Any, max_len: int = MAX_LABEL_LEN) -> str:
  """Shortens a long category label by eliding its middle.

  Keeps the head and tail so long paths stay identifiable by both their
  prefix and their final folder or filename.

  Args:
    label: The raw label; coerced to `str`.
    max_len: Maximum length of the returned label.

  Returns:
    The label, elided with `...` if it exceeded `max_len`.
  """
  text = str(label)
  if len(text) <= max_len:
    return text
  head = (max_len - 3) // 2
  tail = max_len - 3 - head
  return f'{text[:head]}...{text[-tail:]}'


def shorten_index(series: pd.Series,
                  max_len: int = MAX_LABEL_LEN) -> pd.Series:
  """Returns a copy of `series` with short, unique index labels.

  Truncation can make two long paths collide, which would silently merge
  bars, so colliding labels get a numeric suffix.

  Args:
    series: Series whose index holds category labels.
    max_len: Maximum length of each rendered label.

  Returns:
    A new Series with the same values and shortened index labels.
  """
  seen: Dict[str, int] = {}
  labels: List[str] = []
  for raw in series.index:
    text = truncate_label(raw, max_len)
    if text in seen:
      seen[text] += 1
      text = f'{text} ({seen[text]})'
    else:
      seen[text] = 1
    labels.append(text)
  shortened = series.copy()
  shortened.index = labels
  return shortened


def counter_series(counters: Dict[str, Any],
                   name: str,
                   sort: bool = True) -> pd.Series:
  """Builds a Series from a named counter, guarding missing data.

  Args:
    counters: Merged counters across all projects.
    name: Counter key to read.
    sort: Sort descending by count when True, else sort by index.

  Returns:
    A Series of counts, empty when the counter is absent, excluded or
    has no entries.
  """
  if name in EXCLUDED_COUNTERS:
    logger.info("Counter %s is excluded from the report.", name)
    return pd.Series(dtype='int64')
  raw = counters.get(name) or {}
  if not raw:
    return pd.Series(dtype='int64')
  series = pd.Series(raw, dtype='int64')
  if sort:
    return series.sort_values(ascending=False)
  return series.sort_index()


def format_pct(part: float, whole: float) -> str:
  """Formats `part` as a percentage of `whole`.

  Args:
    part: Numerator.
    whole: Denominator; zero yields `n/a`.

  Returns:
    A percentage string such as `61.3%`.
  """
  if not whole:
    return "n/a"
  return f"{100.0 * part / whole:.1f}%"


def counter_table(series: pd.Series,
                  headers: Sequence[str],
                  top_n: int = 20,
                  max_len: int = MAX_TABLE_LABEL_LEN) -> str:
  """Renders a counter Series as a markdown table.

  Args:
    series: Counts indexed by category label.
    headers: Two headers, for the label column and the count column.
    top_n: Maximum number of rows to render.
    max_len: Maximum label length before eliding.

  Returns:
    A markdown table, or an empty string when there is nothing to show.
  """
  if series.empty:
    return ""
  trimmed = shorten_index(series.head(top_n), max_len)
  return trimmed.to_markdown(headers=list(headers))


def plot_bar_counts(counts: pd.Series,
                    title: str,
                    filename: str,
                    xlabel: str,
                    ylabel: str,
                    n: int = 20,
                    sort: bool = True) -> bool:
  """Generate a horizontal bar chart from a Series of counts.

  The figure height scales with the number of bars so labels never
  overlap, long category names are elided, and nothing is written when
  the counter is empty.

  Args:
    counts: Counts indexed by category label.
    title: Plot title.
    filename: Output filename inside the plots directory.
    xlabel: X axis label.
    ylabel: Y axis label.
    n: Maximum number of bars to draw.
    sort: Sort bars descending by count; pass False to keep the given
      order, e.g. for chronological year axes.

  Returns:
    True when a plot file was written, False when data was empty.
  """
  if counts is None or counts.empty:
    logger.warning("Skipping plot '%s': no data.", title)
    return False

  top_n = counts.sort_values(ascending=False).head(n) if sort else counts
  if top_n.empty:
    logger.warning("Skipping plot '%s': no data after filtering.", title)
    return False

  top_n = shorten_index(top_n)
  # Give every bar a fixed slice of vertical space so labels stay
  # legible whether there are 2 categories or 20.
  height = max(4.0, min(14.0, 0.45 * len(top_n) + 1.8))
  plt.figure(figsize=(10, height))

  sns.barplot(x=top_n.values,
              y=top_n.index,
              hue=top_n.index,
              legend=False,
              palette=PALETTE)

  plt.title(title, fontsize=16, weight='bold')
  plt.xlabel(xlabel, fontsize=12)
  plt.ylabel(ylabel, fontsize=12)
  plt.yticks(fontsize=10)
  plt.tight_layout()
  plt.savefig(os.path.join(PLOTS_DIR, filename), dpi=300)
  plt.close()
  return True


def plot_hist(data: pd.Series,
              title: str,
              filename: str,
              xlabel: str,
              bins: int = 20) -> bool:
  """Generate a histogram/KDE plot.

  Args:
    data: Numeric values to bin.
    title: Plot title.
    filename: Output filename inside the plots directory.
    xlabel: X axis label.
    bins: Number of histogram bins.

  Returns:
    True when a plot file was written, False when data was empty.
  """
  if data is None or len(data) == 0:
    logger.warning("Skipping plot '%s': no data.", title)
    return False

  plt.figure(figsize=(10, 6))
  sns.histplot(data,
               bins=bins,
               kde=True,
               color=sns.color_palette(PALETTE, n_colors=1)[0])
  plt.title(title, fontsize=16, weight='bold')
  plt.xlabel(xlabel, fontsize=12)
  plt.ylabel("Count", fontsize=12)
  plt.tight_layout()
  plt.savefig(os.path.join(PLOTS_DIR, filename), dpi=300)
  plt.close()
  return True


def query_projects_by_plugin(project_info: Dict[str, Any], plugin_type: str,
                             preset_name: str) -> list[str]:
  """Finds projects that use a specific plugin and preset."""
  assert plugin_type in [
      'PluginDevice',
      'AuPluginDevice',
  ], f'Invalid plugin type: {plugin_type}'
  matching_projects = [
      f"{fname}-{track['index']}" for fname, v in project_info.items()
      for track in v['tracks'] for dev in track['devices']
      if dev['type'] == plugin_type and dev['preset'] == preset_name
  ]
  return sorted(matching_projects)


def query_projects_with_plugin_type(project_info: Dict[str, Any],
                                    plugin_type: str) -> list[str]:
  """Finds projects that contain a specific plugin type (e.g. Any AU)."""
  assert plugin_type in [
      'PluginDevice',
      'AuPluginDevice',
  ], f'Invalid plugin type: {plugin_type}'

  projects_with_type = [
      fname for fname, project in project_info.items()
      if any(dev['type'] == plugin_type for track in project['tracks']
             for dev in track['devices'])
  ]
  return sorted(projects_with_type)


def scan_for_banned_plugins(project_info: Dict[str, Any],
                            counters: Dict[str, Any]) -> str:
  """Scans for banned or deprecated plugins."""
  report_lines = []
  allow_aus = ['GS-201']  # specific exception from notebook
  deprecated_plugins = ["Ozone 8", "Ozone 6"]

  # Check Deprecated
  report_lines.append("### Deprecated Plugins Check")
  found_deprecated = False
  for vst in deprecated_plugins:
    matches = query_projects_by_plugin(project_info, "PluginDevice", vst)
    if matches:
      found_deprecated = True
      report_lines.append(f"- **{vst}** found in: {', '.join(matches)}")
  if not found_deprecated:
    report_lines.append("No deprecated plugins found.")

  # Check Audio Units (Windows Compatibility)
  report_lines.append("\n### Audio Unit (AU) Compatibility Check")
  report_lines.append(
      "> These projects use Audio Units instead of VSTs, which may not "
      "load on Windows.")

  if 'plugins_au' in counters:
    for au, _ in counters['plugins_au'].items():
      if au in allow_aus:
        continue
      matches = query_projects_by_plugin(project_info, "AuPluginDevice", au)
      if matches:
        report_lines.append(f"- **{au}** found in: {', '.join(matches)}")

  return "\n".join(report_lines)


def build_sample_dataframe(project_info: Dict[str, Any]) -> pd.DataFrame:
  """Flattens every sample reference across all projects into a table.

  Args:
    project_info: Parsed project information.

  Returns:
    A DataFrame with one row per sample reference, or an empty frame when
    the parsed data predates sample extraction.
  """
  rows = []
  for project in project_info.values():
    if not isinstance(project, dict) or 'error' in project:
      continue
    for sample in project.get('samples', []) or []:
      rows.append({
          'project': project.get('name'),
          'name': sample.get('name'),
          'extension': sample.get('extension'),
          'source': sample.get('source'),
          'duration_sec': sample.get('duration_sec'),
          'sample_rate': sample.get('sample_rate'),
          'exists_on_disk': sample.get('exists_on_disk'),
      })
  return pd.DataFrame(rows)


def build_warp_marker_series(project_info: Dict[str, Any]) -> pd.Series:
  """Collects warp-marker totals per project.

  The parser stores warp markers as a single `total` bucket per project,
  so per-project values are recovered from the project records rather
  than from the merged counters.

  Args:
    project_info: Parsed project information.

  Returns:
    Warp-marker totals indexed by project name, empty when no project
    contains warped audio.
  """
  totals: Dict[str, int] = {}
  for key, project in project_info.items():
    if not isinstance(project, dict) or 'error' in project:
      continue
    counters = project.get('counters') or {}
    warp = counters.get('warp_markers') or {}
    total = int(warp.get('total', 0))
    if total:
      totals[str(project.get('name', key))] = total
  if not totals:
    return pd.Series(dtype='int64')
  return pd.Series(totals, dtype='int64').sort_values(ascending=False)


def build_sample_section(samples_df: pd.DataFrame) -> str:
  """Renders aggregate sample statistics as markdown.

  Reports distributions and counts only. Absolute sample paths are
  deliberately excluded so the section stays safe to share.

  Args:
    samples_df: Output of `build_sample_dataframe`.

  Returns:
    A markdown fragment describing the sample library.
  """
  if samples_df.empty:
    return ("No sample data available. Re-run the parser to populate "
            "sample references.")

  lines = []
  total = len(samples_df)
  unique = samples_df['name'].nunique()
  lines.append(f"- **Total sample references:** {total:,}")
  lines.append(f"- **Unique sample files:** {unique:,}")
  reuse = total / unique if unique else 0
  lines.append(f"- **Average reuse per sample:** {reuse:.1f}x")

  if 'duration_sec' in samples_df.columns:
    durations = samples_df['duration_sec'].dropna()
    if not durations.empty:
      lines.append(f"- **Median sample length:** {durations.median():.2f}s")
      lines.append(f"- **Total sampled audio:** {durations.sum() / 3600:.1f} "
                   "hours (with repeats)")

  missing = samples_df['exists_on_disk'].eq(False).sum()
  if missing:
    lines.append(f"- **Missing from disk:** {missing:,} "
                 "(run with `--probe-samples` to refresh)")

  # Where samples enter the set: clips vs instrument devices.
  if 'source' in samples_df.columns:
    source_counts = samples_df['source'].value_counts()
    lines.append("\n#### Sample Source")
    lines.append(
        "> Samples reach a set either as audio clips, from inside "
        "Simpler / Sampler / Drum Rack devices, or from kits loaded "
        "inside plugins.\n")
    lines.append(source_counts.to_markdown(headers=["Source", "Count"]))

  if 'extension' in samples_df.columns:
    ext_counts = samples_df['extension'].value_counts().head(10)
    if not ext_counts.empty:
      lines.append("\n#### File Formats")
      lines.append(ext_counts.to_markdown(headers=["Format", "Count"]))

  # Most re-used samples across the whole library.
  top_samples = samples_df.groupby('name')['project'].nunique().sort_values(
      ascending=False).head(20)
  if not top_samples.empty:
    lines.append("\n#### Most Re-used Samples (by project count)")
    lines.append(top_samples.to_markdown(headers=["Sample", "Projects"]))

  # Which projects lean hardest on samples.
  per_project = samples_df.groupby('project').size().sort_values(
      ascending=False).head(20)
  if not per_project.empty:
    lines.append("\n#### Most Sample-Heavy Projects")
    lines.append(per_project.to_markdown(headers=["Project", "Samples"]))

  return "\n".join(lines)


def build_device_section(counters: Dict[str, Any]) -> str:
  """Renders instrument/effect/plugin composition as markdown.

  Args:
    counters: Merged counters across all projects.

  Returns:
    A markdown fragment describing device usage.
  """
  lines = []
  kinds = counters.get('device_kinds', {})
  if kinds:
    kind_series = pd.Series(kinds).sort_values(ascending=False)
    lines.append("#### Device Composition")
    lines.append(kind_series.to_markdown(headers=["Kind", "Count"]))

  effects = counters.get('effects', {})
  if effects:
    effect_series = pd.Series(effects).sort_values(ascending=False).head(20)
    lines.append("\n#### Top Audio Effects")
    lines.append(effect_series.to_markdown(headers=["Effect", "Count"]))

  instruments = counters.get('instruments', {})
  if instruments:
    inst_series = pd.Series(instruments).sort_values(ascending=False).head(20)
    lines.append("\n#### Top Instruments")
    lines.append(inst_series.to_markdown(headers=["Instrument", "Count"]))

  if not lines:
    return "No device data available."
  return "\n".join(lines)


def build_plugin_content_section(counters: Dict[str, Any]) -> str:
  """Renders sample content carried inside plugins as markdown.

  Covers `vst_libraries`, `plugins_with_samples`, `plugin_sample_kits`,
  `plugin_sample_files`, `au_presets` and `vst_strings`.

  Args:
    counters: Merged counters across all projects.

  Returns:
    A markdown fragment, or a short notice when no plugin carried
    recoverable sample content.
  """
  lines: List[str] = []

  libraries = counter_series(counters, 'vst_libraries')
  if not libraries.empty:
    lines.append("#### Sample Libraries in Use")
    lines.append(
        f"> {len(libraries):,} distinct libraries referenced across "
        f"{int(libraries.sum()):,} plugin instances.\n")
    lines.append(counter_table(libraries, ["Library", "References"]))

  plugins_with_samples = counter_series(counters, 'plugins_with_samples')
  if not plugins_with_samples.empty:
    lines.append("\n#### Plugins Carrying Sample Content")
    lines.append(
        "> Plugins whose saved state contains internal sample paths. "
        "Their audio does not live in the Ableton set, so it is easy to "
        "miss when archiving a project.\n")
    lines.append(counter_table(plugins_with_samples,
                               ["Plugin", "Instances"]))

  kits = counter_series(counters, 'plugin_sample_kits')
  if not kits.empty:
    lines.append("\n#### Most Referenced Plugin Kit Folders")
    lines.append(
        f"> {len(kits):,} distinct kit folders. Each row is a folder of "
        "samples loaded by a plugin, collapsed from the per-file rows.\n")
    lines.append(counter_table(kits, ["Kit Folder", "References"]))

  plugin_files = counter_series(counters, 'plugin_sample_files')
  if not plugin_files.empty:
    lines.append("\n#### Most Used Samples Inside Plugins")
    lines.append(
        f"> {len(plugin_files):,} distinct filenames recovered from "
        "plugin state, kept at counter level so filename search still "
        "works after kit collapsing.\n")
    lines.append(counter_table(plugin_files, ["Sample File", "Uses"]))

  au_presets = counter_series(counters, 'au_presets')
  if not au_presets.empty:
    lines.append("\n#### Audio Unit Presets")
    lines.append(
        "> AU presets are stored as readable names, unlike opaque VST "
        "plugin state, so these are reported verbatim.\n")
    lines.append(counter_table(au_presets, ["Plugin: Preset", "Count"]))

  vst_strings = counter_series(counters, 'vst_strings')
  if not vst_strings.empty:
    lines.append("\n#### Recovered Plugin State Strings")
    lines.append(
        f"> {len(vst_strings):,} distinct strings recovered from "
        f"{int(vst_strings.sum()):,} plugin instances.\n")
    lines.append(VST_STRINGS_CAVEAT)
    lines.append(counter_table(vst_strings, ["Plugin: String", "Count"]))

  if not lines:
    return ("No plugin-internal sample content was recovered. This is "
            "expected when projects use only stock devices.")
  return "\n".join(lines)


def build_locators_section(counters: Dict[str, Any]) -> str:
  """Renders arrangement locators / section markers as markdown.

  Args:
    counters: Merged counters across all projects.

  Returns:
    A markdown fragment listing the most common arrangement locators,
    or a notice when none were found.
  """
  locators = counter_series(counters, 'locators')
  if locators.empty:
    return ("No arrangement locators were found. This is normal for sets "
            "constructed purely in Session view or without section labels.")
  lines = [
      f"> {len(locators):,} distinct locator names used across "
      f"{int(locators.sum()):,} arrangement points. These section markers "
      "(e.g. verse, drop, choruses) highlight natural rip and chop points.\n"
  ]
  lines.append(counter_table(locators, ["Locator / Section", "Count"]))
  return "\n".join(lines)


def build_missing_samples_section(counters: Dict[str, Any],
                                  samples_df: pd.DataFrame) -> str:
  """Renders broken sample references as an actionable markdown section.

  Args:
    counters: Merged counters across all projects.
    samples_df: Output of `build_sample_dataframe`.

  Returns:
    A markdown fragment listing missing samples, or a notice explaining
    why none are listed.
  """
  missing = counter_series(counters, 'samples_missing')
  if missing.empty:
    if samples_df.empty or samples_df['exists_on_disk'].isna().all():
      return ("Sample existence was not checked. Re-run the parser with "
              "`--probe-samples` to detect broken references.")
    return "No broken sample references found. Every sample resolved."

  total_refs = int(missing.sum())
  lines = [
      f"- **Distinct missing samples:** {len(missing):,}",
      f"- **Broken references:** {total_refs:,}",
  ]

  if not samples_df.empty and 'exists_on_disk' in samples_df.columns:
    checked = int(samples_df['exists_on_disk'].notna().sum())
    if checked:
      broken = int(samples_df['exists_on_disk'].eq(False).sum())
      lines.append(f"- **Share of checked references broken:** "
                   f"{format_pct(broken, checked)}")
    affected = samples_df.loc[samples_df['exists_on_disk'].eq(False),
                              'project'].nunique()
    if affected:
      lines.append(f"- **Projects affected:** {affected:,}")

  lines.append("")
  lines.append(
      "> Each row below is a file an Ableton set still points at but "
      "that no longer resolves on disk. Restore or re-link these before "
      "archiving the affected projects.\n")
  lines.append(counter_table(missing, ["Missing Sample", "References"]))

  if not samples_df.empty and 'exists_on_disk' in samples_df.columns:
    broken_rows = samples_df.loc[samples_df['exists_on_disk'].eq(False)]
    if not broken_rows.empty:
      worst = broken_rows.groupby('project').size().sort_values(
          ascending=False).head(20)
      lines.append("\n#### Projects With the Most Broken References")
      lines.append(counter_table(worst, ["Project", "Broken References"]))

  return "\n".join(lines)


def build_clip_section(counters: Dict[str, Any],
                       warp_series: pd.Series) -> str:
  """Renders audio clip looping and warping statistics as markdown.

  Args:
    counters: Merged counters across all projects.
    warp_series: Warp-marker totals per project.

  Returns:
    A markdown fragment covering `audio_clip_is_loop` and
    `warp_markers`, or a notice when neither counter fired.
  """
  lines: List[str] = []

  loops = counter_series(counters, 'audio_clip_is_loop')
  if not loops.empty:
    total_clips = int(loops.sum())
    looped = int(loops.get('True', 0))
    lines.append("#### Loop vs One-Shot Balance")
    lines.append(
        f"> {looped:,} of {total_clips:,} audio clips loop "
        f"({format_pct(looped, total_clips)}). The remainder play once, "
        "which is the signature of one-shot or chopped material.\n")
    renamed = loops.rename(index={'True': 'Looping', 'False': 'One-shot'})
    lines.append(renamed.to_markdown(headers=["Clip Mode", "Clips"]))

  if not warp_series.empty:
    total_markers = int(warp_series.sum())
    lines.append("\n#### Warp Marker Density")
    lines.append(
        f"> {total_markers:,} warp markers across "
        f"{len(warp_series):,} projects "
        f"(median {warp_series.median():.0f} per warped project). Dense "
        "warping usually indicates hand-aligned or heavily edited "
        "audio.\n")
    lines.append(counter_table(warp_series, ["Project", "Warp Markers"]))

  if not lines:
    return ("No audio clip data available. Loop and warp statistics "
            "require projects containing audio clips.")
  return "\n".join(lines)


def build_analysis_section(counters: Dict[str, Any],
                           samples_df: pd.DataFrame,
                           warp_series: pd.Series,
                           df: pd.DataFrame) -> str:
  """Renders the narrative findings that the tables only imply.

  Args:
    counters: Merged counters across all projects.
    samples_df: Output of `build_sample_dataframe`.
    warp_series: Warp-marker totals per project.
    df: One row per project.

  Returns:
    A markdown fragment of prose findings, or a notice when there is not
    enough data to draw any.
  """
  findings: List[str] = []

  # Finding 1: where samples actually come from. An extractor that only
  # walked audio clips would miss everything nested in devices and
  # plugins, which is the majority of the library.
  sources = counter_series(counters, 'sample_sources')
  if not sources.empty:
    total = int(sources.sum())
    hidden = int(sum(int(sources.get(src, 0)) for src in NON_CLIP_SOURCES))
    clip_refs = total - hidden
    findings.append(
        f"**Most samples are not audio clips.** Device and plugin "
        f"sources account for {hidden:,} of {total:,} sample references "
        f"({format_pct(hidden, total)}), against {clip_refs:,} "
        f"({format_pct(clip_refs, total)}) from audio clips. An "
        "audio-clip-only extractor would miss the majority of the "
        "sample library, so device chains and plugin state both have to "
        "be walked.")

  # Finding 2: how concentrated the sample library is.
  libraries = counter_series(counters, 'vst_libraries')
  if not libraries.empty:
    lib_total = int(libraries.sum())
    top_share = format_pct(int(libraries.iloc[0]), lib_total)
    cumulative = libraries.cumsum()
    covering = int((cumulative < 0.8 * lib_total).sum()) + 1
    findings.append(
        f"**Library use is concentrated.** {len(libraries):,} distinct "
        f"sample libraries appear, but the largest alone covers "
        f"{top_share} of all library references and just {covering} "
        f"libraries cover 80% of them. Archiving that short list "
        "preserves most of the sample material.")

  # Finding 3: format mix, including how much of it is lossy.
  extensions = counter_series(counters, 'sample_extensions')
  if not extensions.empty:
    ext_total = int(extensions.sum())
    dominant = str(extensions.index[0])
    dominant_share = format_pct(int(extensions.iloc[0]), ext_total)
    lossy = int(
        sum(int(count) for ext, count in extensions.items()
            if str(ext).lower() in LOSSY_EXTENSIONS))
    lossy_note = (
        f" Lossy formats make up {format_pct(lossy, ext_total)} of "
        "references, which caps the quality ceiling on that material."
        if lossy else
        " No lossy formats appear, so the library is uncompressed "
        "throughout.")
    findings.append(
        f"**Format mix is dominated by `{dominant}`** at "
        f"{dominant_share} of {ext_total:,} references across "
        f"{len(extensions):,} formats.{lossy_note}")

  # Finding 4: sample reuse, i.e. palette breadth versus depth.
  if not samples_df.empty:
    total_refs = len(samples_df)
    unique = samples_df['name'].nunique()
    if unique:
      reuse = total_refs / unique
      per_project = samples_df.groupby('project').size()
      shared = samples_df.groupby('name')['project'].nunique()
      cross = int((shared > 1).sum())
      findings.append(
          f"**Samples are reused across projects.** {unique:,} distinct "
          f"files back {total_refs:,} references ({reuse:.1f}x reuse), "
          f"and {cross:,} files appear in more than one project. The "
          f"median project pulls in {per_project.median():.0f} samples "
          f"while the heaviest pulls {per_project.max():,}.")

  # Finding 5: plugin-held content is invisible to a set-only backup.
  plugins_with_samples = counter_series(counters, 'plugins_with_samples')
  kits = counter_series(counters, 'plugin_sample_kits')
  if not plugins_with_samples.empty:
    findings.append(
        f"**Plugin-held audio is a portability risk.** "
        f"{len(plugins_with_samples):,} plugins carry internal sample "
        f"references spanning {len(kits):,} kit folders. None of that "
        "audio is stored in the Ableton set, so copying only the "
        "project folder silently drops it.")

  # Finding 6: what the opaque plugin state actually yields. Stated with
  # its caveat so nobody reads the table as a clean preset list.
  vst_strings = counter_series(counters, 'vst_strings')
  if not vst_strings.empty:
    findings.append(
        f"**Plugin state is partially readable.** {len(vst_strings):,} "
        f"distinct strings were recovered from otherwise opaque plugin "
        f"chunks across {int(vst_strings.sum()):,} instances. These mix "
        "true preset names with plugin parameter labels, so treat them "
        "as recovered state strings rather than a preset inventory.")

  # Finding 7: loop balance and warping effort.
  loops = counter_series(counters, 'audio_clip_is_loop')
  if not loops.empty:
    total_clips = int(loops.sum())
    looped = int(loops.get('True', 0))
    lean = 'looped' if looped * 2 >= total_clips else 'one-shot'
    warp_note = ""
    if not warp_series.empty:
      warp_note = (f" Warping is hand-tuned in {len(warp_series):,} "
                   f"projects, totalling {int(warp_series.sum()):,} warp "
                   "markers.")
    findings.append(
        f"**Clip usage leans {lean}.** "
        f"{format_pct(looped, total_clips)} of {total_clips:,} audio "
        f"clips loop.{warp_note}")

  # Finding 7: broken references, stated up front because they are the
  # only finding that demands action.
  missing = counter_series(counters, 'samples_missing')
  if not missing.empty:
    findings.append(
        f"**{len(missing):,} sample files no longer resolve on disk**, "
        f"covering {int(missing.sum()):,} references. See the Missing "
        "Samples section for the full list.")

  # Finding 8: catalogue scale, for context.
  if not df.empty:
    scale = f"**Catalogue scale:** {len(df):,} projects parsed"
    if 'num_tracks' in df.columns:
      tracks = df['num_tracks'].dropna()
      if not tracks.empty:
        scale += f", {int(tracks.sum()):,} tracks"
    if 'file_size_mb' in df.columns:
      size = df['file_size_mb'].dropna()
      if not size.empty:
        scale += f", {size.sum():.1f} MB of set files"
    findings.append(scale + ".")

  if not findings:
    return "Not enough parsed data to draw any findings."
  return "\n".join(f"- {finding}" for finding in findings)


def render_counter_plots(counters: Dict[str, Any],
                         warp_series: pd.Series) -> Set[str]:
  """Writes the counter-driven plots, skipping empty counters.

  Args:
    counters: Merged counters across all projects.
    warp_series: Warp-marker totals per project.

  Returns:
    The set of plot filenames that were actually written.
  """
  written: Set[str] = set()

  # (counter name, title, filename, x label, y label, top-n)
  bar_plots: Tuple[Tuple[str, str, str, str, str, int], ...] = (
      ('vst_libraries', "Top Sample Libraries", "sample_libraries.png",
       "References", "Library", 20),
      ('plugins_with_samples', "Plugins Carrying Sample Content",
       "plugins_with_samples.png", "Instances", "Plugin", 20),
      ('plugin_sample_kits', "Most Referenced Plugin Kit Folders",
       "plugin_sample_kits.png", "References", "Kit Folder", 20),
      ('plugin_sample_files', "Most Used Samples Inside Plugins",
       "plugin_sample_files.png", "Uses", "Sample File", 20),
      ('au_presets', "Top Audio Unit Presets", "au_presets.png", "Count",
       "Plugin: Preset", 20),
      ('samples_missing', "Most Referenced Missing Samples",
       "samples_missing.png", "Broken References", "Sample", 20),
      ('vst_strings', "Recovered Plugin State Strings",
       "vst_preset_strings.png", "Count", "Plugin: String", 20),
      ('locators', "Most Common Arrangement Locators",
       "locators.png", "Count", "Locator / Section", 20),
  )
  # Anything listed in EXCLUDED_COUNTERS yields an empty Series here, so
  # a blocked counter silently produces no plot.
  for name, title, filename, xlabel, ylabel, top_n in bar_plots:
    series = counter_series(counters, name)
    if plot_bar_counts(series, title, filename, xlabel, ylabel, n=top_n):
      written.add(filename)

  loops = counter_series(counters, 'audio_clip_is_loop')
  if not loops.empty:
    renamed = loops.rename(index={'True': 'Looping', 'False': 'One-shot'})
    if plot_bar_counts(renamed, "Audio Clips: Loop vs One-Shot",
                       "audio_clip_loops.png", "Clips", "Clip Mode", n=5):
      written.add("audio_clip_loops.png")

  if not warp_series.empty:
    if plot_hist(warp_series, "Warp Markers per Project",
                 "warp_markers.png", "Warp Markers", bins=30):
      written.add("warp_markers.png")
    if plot_bar_counts(warp_series.head(20), "Most Heavily Warped Projects",
                       "warp_markers_top.png", "Warp Markers", "Project",
                       n=20):
      written.add("warp_markers_top.png")

  return written


def render_graph_links(sections: Iterable[Tuple[str, str]],
                       written: Set[str]) -> List[str]:
  """Builds markdown image links for plots that exist.

  Args:
    sections: Pairs of (heading, plot filename).
    written: Filenames that were actually written this run.

  Returns:
    A list of markdown fragments, one per available plot.
  """
  links: List[str] = []
  for heading, filename in sections:
    if filename not in written:
      logger.info("Omitting graph '%s': plot not generated.", heading)
      continue
    path = f"{PLOTS_DIR}/{filename}"
    stem = os.path.splitext(filename)[0]
    links.append(f"#### {heading}\n![{stem}]({path})\n")
  return links


def generate_markdown(project_info: Dict[str, Any],
                      df: pd.DataFrame) -> None:
  """Generates the detailed Markdown report and writes it to REPORT.md.

  REPORT.md is gitignored by the public repository and is carried only by
  the private remote, so it may contain project-level detail.

  Args:
    project_info: Parsed project information keyed by project file.
    df: One row per project, used for the inventory and distributions.
  """
  os.makedirs(PLOTS_DIR, exist_ok=True)

  # Data Processing
  counters = save_counters(project_info)

  vst_counts = counter_series(counters, 'plugins_vst')
  au_counts = counter_series(counters, 'plugins_au')

  counters_snapshot = {
      'plugins_au': counters.get('plugins_au', {}),
      'plugins_vst': counters.get('plugins_vst', {})
  }

  # Every plot records itself here so the Graphs section never links to
  # an image that was skipped for lack of data.
  written: Set[str] = set()

  # Plotting

  # Ableton Version
  version_series = counter_series(counters, 'ableton_version', sort=False)
  if plot_bar_counts(version_series.sort_index(ascending=False),
                     "Ableton Version Distribution",
                     "ableton_version.png",
                     "Count",
                     "Version",
                     n=30,
                     sort=False):
    written.add("ableton_version.png")

  # Tracks per Project
  if 'num_tracks' in df.columns:
    if plot_hist(df['num_tracks'].dropna(), "Tracks per Project",
                 "tracks_dist.png", "Number of Tracks"):
      written.add("tracks_dist.png")

  # File Size
  if 'file_size_mb' in df.columns:
    if plot_hist(df['file_size_mb'].dropna(),
                 "Project File Size (MB)",
                 "filesize_dist.png",
                 "Size (MB)",
                 bins=30):
      written.add("filesize_dist.png")

  # Creation Year
  if plot_bar_counts(counter_series(counters, 'creation_year', sort=False),
                     "Projects by Creation Year",
                     "creation_year.png",
                     "Count",
                     "Year",
                     n=50,
                     sort=False):
    written.add("creation_year.png")

  # Last Modified Year
  wrote_modified_year = plot_bar_counts(
      counter_series(counters, 'last_modified_year', sort=False),
      "Projects by Last Modified Year",
      "last_modified_year.png",
      "Count",
      "Year",
      n=50,
      sort=False)
  if wrote_modified_year:
    written.add("last_modified_year.png")

  # Track Types
  if plot_bar_counts(counter_series(counters, 'track_types'),
                     "Track Types",
                     "track_types.png",
                     "Count",
                     "Track Type",
                     n=10):
    written.add("track_types.png")

  # Device Types
  if plot_bar_counts(counter_series(counters, 'device_types'),
                     "Top 20 Device Types",
                     "device_types.png",
                     "Count",
                     "Device Type",
                     n=20):
    written.add("device_types.png")

  # Top VST Plugins
  if plot_bar_counts(vst_counts, "Top 20 VST Plugins", "top_vst.png",
                     "Count", "Plugin Name"):
    written.add("top_vst.png")

  # Top AU Plugins
  if plot_bar_counts(au_counts, "Top 20 AU Plugins", "top_au.png", "Count",
                     "Plugin Name"):
    written.add("top_au.png")

  # Tempo
  if 'tempo' in df.columns:
    if plot_hist(df['tempo'].dropna(),
                 "Tempo Distribution",
                 "tempo_dist.png",
                 "BPM",
                 bins=20):
      written.add("tempo_dist.png")

  # Markdown Tables
  vst_table = (counter_table(vst_counts, ["Plugin", "Count"])
               or "No VSTs found.")
  au_table = (counter_table(au_counts, ["Plugin", "Count"])
              or "No AUs found.")

  # Project Inventory
  if not df.empty and 'modified' in df.columns:
    inventory_cols = [
        'name', 'ableton_version_full', 'tempo', 'scale_root', 'scale_name',
        'duration_sec', 'num_tracks', 'file_size_mb', 'modified'
    ]
    cols = [c for c in inventory_cols if c in df.columns]
    inventory_df = df.sort_values('modified', ascending=False).head(50)[cols]
    if 'modified' in inventory_df.columns:
      inventory_df['modified'] = inventory_df['modified'].astype(str)

    inventory_table = inventory_df.to_markdown(index=False,
                                               tablefmt="github")
  else:
    inventory_table = "No project data available."

  # Plugin Analysis
  plugin_analysis = scan_for_banned_plugins(project_info, counters_snapshot)

  # Sample Analysis (new)
  samples_df = build_sample_dataframe(project_info)
  warp_series = build_warp_marker_series(project_info)
  sample_section = build_sample_section(samples_df)
  device_section = build_device_section(counters)
  plugin_content_section = build_plugin_content_section(counters)
  missing_section = build_missing_samples_section(counters, samples_df)
  locators_section = build_locators_section(counters)
  clip_section = build_clip_section(counters, warp_series)
  analysis_section = build_analysis_section(counters, samples_df,
                                            warp_series, df)

  written |= render_counter_plots(counters, warp_series)

  # Sample-oriented plots
  if not samples_df.empty:
    ext_counts = samples_df['extension'].value_counts()
    if plot_bar_counts(ext_counts,
                       "Sample Formats",
                       "sample_formats.png",
                       "Count",
                       "Format",
                       n=10):
      written.add("sample_formats.png")

    per_project_counts = samples_df.groupby('project').size()
    if plot_hist(per_project_counts,
                 "Samples per Project",
                 "samples_per_project.png",
                 "Number of Samples",
                 bins=30):
      written.add("samples_per_project.png")

    source_counts = samples_df['source'].value_counts()
    if plot_bar_counts(source_counts,
                       "Where Samples Come From",
                       "sample_sources.png",
                       "References",
                       "Source",
                       n=10):
      written.add("sample_sources.png")

    durations = samples_df['duration_sec'].dropna()
    # Clip the long tail so the useful range stays readable.
    durations = durations[durations.between(0, 60)]
    if plot_hist(durations,
                 "Sample Length Distribution (0-60s)",
                 "sample_duration.png",
                 "Duration (seconds)",
                 bins=40):
      written.add("sample_duration.png")

  # Report Construction
  report_content = []
  report_content.append(f"**Generated:** {pd.Timestamp.now()}\n")

  report_content.append("### Overview")
  report_content.append(f"- **Total Projects:** {len(df)}")
  if 'file_size_mb' in df.columns:
    report_content.append(
        f"- **Total Size:** {df['file_size_mb'].sum():.2f} MB")
  if not samples_df.empty:
    report_content.append(
        f"- **Total Sample References:** {len(samples_df):,}")
    report_content.append(
        f"- **Unique Samples:** {samples_df['name'].nunique():,}")
  if not df.empty and 'created' in df.columns:
    report_content.append(
        f"- **Date Range:** {df['created'].min()} to {df['created'].max()}\n")

  report_content.append("### Key Findings")
  report_content.append(f"{analysis_section}\n")

  report_content.append("### Potential Compatibility Issues")
  report_content.append(f"{plugin_analysis}\n")

  report_content.append("### Top Plugins")
  report_content.append(f"#### VST\n\n{vst_table}\n")
  report_content.append(f"#### AU\n\n{au_table}\n")

  report_content.append("### Device Composition")
  report_content.append(f"{device_section}\n")

  report_content.append("### Sample Library")
  report_content.append(f"{sample_section}\n")

  report_content.append("### Plugin Sample Content")
  report_content.append(f"{plugin_content_section}\n")

  report_content.append("### Missing Samples")
  report_content.append(f"{missing_section}\n")

  report_content.append("### Clip Looping and Warping")
  report_content.append(f"{clip_section}\n")

  report_content.append("### Arrangement Locators")
  report_content.append(f"{locators_section}\n")

  report_content.append("### Project Inventory (Top 50 Recently Modified)")
  report_content.append(f"{inventory_table}\n")

  graph_sections = (
      ("Ableton Version", "ableton_version.png"),
      ("Creation Year", "creation_year.png"),
      ("Last Modified Year", "last_modified_year.png"),
      ("Track Types", "track_types.png"),
      ("Tracks per Project", "tracks_dist.png"),
      ("Device Types (Top 20)", "device_types.png"),
      ("File Size", "filesize_dist.png"),
      ("Tempo Distribution", "tempo_dist.png"),
      ("Top VSTs", "top_vst.png"),
      ("Top AUs", "top_au.png"),
      ("Sample Sources", "sample_sources.png"),
      ("Sample Formats", "sample_formats.png"),
      ("Samples per Project", "samples_per_project.png"),
      ("Sample Length", "sample_duration.png"),
      ("Sample Libraries", "sample_libraries.png"),
      ("Plugins Carrying Samples", "plugins_with_samples.png"),
      ("Plugin Kit Folders", "plugin_sample_kits.png"),
      ("Samples Inside Plugins", "plugin_sample_files.png"),
      ("Audio Unit Presets", "au_presets.png"),
      ("Plugin State Strings", "vst_preset_strings.png"),
      ("Missing Samples", "samples_missing.png"),
      ("Arrangement Locators", "locators.png"),
      ("Loop vs One-Shot", "audio_clip_loops.png"),
      ("Warp Markers per Project", "warp_markers.png"),
      ("Most Warped Projects", "warp_markers_top.png"),
  )
  graph_links = render_graph_links(graph_sections, written)
  if graph_links:
    report_content.append("### Graphs")
    report_content.extend(graph_links)

  full_report = "\n".join(report_content)
  write_report_file(full_report)


def write_report_file(report_content: str) -> None:
  """Writes the generated report to REPORT.md.

  Args:
    report_content: The rendered markdown body.
  """
  report_path = 'REPORT.md'
  try:
    with open(report_path, 'w', encoding='utf-8') as f:
      f.write("# Ableton Project Parser - Detailed Report\n\n")
      f.write(report_content)
    logger.info("Successfully wrote report to %s", report_path)
  except OSError as e:
    logger.error("Failed to write report to %s: %s", report_path, e)


if __name__ == '__main__':
  data = load_data(CACHE_FILE)
  if data:
    # Convert to DF for easier handling
    df_list = []
    for key, p in data.items():
      p['name'] = p.get('name', key)
      df_list.append(p)
    df = pd.DataFrame(df_list)

    generate_markdown(data, df)
    logger.info("Report generated successfully.")
  else:
    logger.error("Failed to load data.")
