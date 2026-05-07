
import logging
import os
import pickle
from typing import Any, Dict
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


def generate_markdown_table(data: Any, headers: list[str] | None = None) -> str:
  """Generate a markdown table from a DataFrame or Series."""
  if isinstance(data, pd.Series):
      data = data.to_frame(name=headers[1] if headers and len(headers) > 1 else 'Count')

  if headers and isinstance(data, pd.DataFrame):
      # If headers provided, we might need to handle index resetting outside or here
      # But basic usage:
      return data.to_markdown(headers=headers, tablefmt="github")

  if hasattr(data, 'to_markdown'):
      return data.to_markdown(tablefmt="github")

  return str(data)


def load_data(cache_file: str) -> Dict[str, Any]:
  """Load project data from pickle."""
  if not os.path.exists(cache_file):
    print(f"Error: Cache file {cache_file} not found.")
    return {}
  with open(cache_file, 'rb') as f:
    return pickle.load(f)


def plot_bar_counts(counts: pd.Series,
                    title: str,
                    filename: str,
                    xlabel: str,
                    ylabel: str,
                    n: int = 20):
  """Generate a horizontal bar chart from a Series of counts."""
  plt.figure(figsize=(10, 8))
  top_n = counts.head(n)

  if top_n.empty:
    logger.warning(f"No data for {title}")
    plt.close()
    return

  sns.barplot(x=top_n.values,
              y=top_n.index,
              hue=top_n.index,
              legend=False,
              palette=PALETTE)

  plt.title(title, fontsize=16, weight='bold')
  plt.xlabel(xlabel, fontsize=12)
  plt.ylabel(ylabel, fontsize=12)
  plt.tight_layout()
  plt.savefig(os.path.join(PLOTS_DIR, filename), dpi=300)
  plt.close()


def plot_hist(data: pd.Series,
              title: str,
              filename: str,
              xlabel: str,
              bins: int = 20):
  """Generate a histogram/KDE plot."""
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
      "> These projects use Audio Units instead of VSTs, which may not load on Windows."
  )

  if 'plugins_au' in counters:
    for au, _ in counters['plugins_au'].items():
      if au in allow_aus:
        continue
      matches = query_projects_by_plugin(project_info, "AuPluginDevice", au)
      if matches:
        report_lines.append(f"- **{au}** found in: {', '.join(matches)}")

  return "\n".join(report_lines)


def generate_markdown(project_info: Dict[str, Any], df: pd.DataFrame):
  """Generate the Markdown report and inject it into README."""
  os.makedirs(PLOTS_DIR, exist_ok=True)

  # Data Processing
  counters = save_counters(project_info)

  vst_counts = pd.Series(counters.get('plugins_vst',
                                      {})).sort_values(ascending=False)
  au_counts = pd.Series(counters.get('plugins_au',
                                     {})).sort_values(ascending=False)

  counters_snapshot = {
      'plugins_au': counters.get('plugins_au', {}),
      'plugins_vst': counters.get('plugins_vst', {})
  }

  # Plotting

  # Ableton Version
  if 'ableton_version' in counters:
    sorted_vers = pd.Series(counters['ableton_version']).sort_index(
        ascending=False)
    plot_bar_counts(sorted_vers, "Ableton Version Distribution",
                    "ableton_version.png", "Count", "Version")

  # Tracks per Project
  if 'num_tracks' in df.columns:
    plot_hist(df['num_tracks'], "Tracks per Project", "tracks_dist.png",
              "Number of Tracks")

  # File Size
  if 'file_size_mb' in df.columns:
    plot_hist(df['file_size_mb'],
              "Project File Size (MB)",
              "filesize_dist.png",
              "Size (MB)",
              bins=30)

  # Creation Year
  if 'creation_year' in counters:
    sorted_creation = pd.Series(counters['creation_year']).sort_index()
    plot_bar_counts(sorted_creation, "Projects by Creation Year",
                    "creation_year.png", "Count", "Year")

  # Last Modified Year
  if 'last_modified_year' in counters:
    sorted_modified = pd.Series(counters['last_modified_year']).sort_index()
    plot_bar_counts(sorted_modified, "Projects by Last Modified Year",
                    "last_modified_year.png", "Count", "Year")

  # Device Types
  if 'device_types' in counters:
    device_counts = pd.Series(counters['device_types']).sort_values(
        ascending=False)
    plot_bar_counts(device_counts,
                    "Top 20 Device Types",
                    "device_types.png",
                    "Count",
                    "Device Type",
                    n=20)

  # Top VST Plugins
  if not vst_counts.empty:
    plot_bar_counts(vst_counts, "Top 20 VST Plugins", "top_vst.png", "Count",
                    "Plugin Name")

  # Top AU Plugins
  if not au_counts.empty:
    plot_bar_counts(au_counts, "Top 20 AU Plugins", "top_au.png", "Count",
                    "Plugin Name")

  # Tempo
  if 'tempo' in df.columns:
    plot_hist(df['tempo'].dropna(),
              "Tempo Distribution",
              "tempo_dist.png",
              "BPM",
              bins=20)

  # Markdown Tables
  vst_table = vst_counts.head(20).to_markdown(
      headers=["Plugin", "Count"]) if not vst_counts.empty else "No VSTs found."
  au_table = au_counts.head(20).to_markdown(
      headers=["Plugin", "Count"]) if not au_counts.empty else "No AUs found."

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

    inventory_table = inventory_df.to_markdown(index=False, tablefmt="github")
  else:
    inventory_table = "No project data available."

  # Plugin Analysis
  plugin_analysis = scan_for_banned_plugins(project_info, counters_snapshot)

  # Report Construction
  report_content = []
  report_content.append(f"**Generated:** {pd.Timestamp.now()}\n")

  report_content.append("### Overview")
  report_content.append(f"- **Total Projects:** {len(df)}")
  if 'file_size_mb' in df.columns:
    report_content.append(
        f"- **Total Size:** {df['file_size_mb'].sum():.2f} MB")
  if not df.empty and 'created' in df.columns:
    report_content.append(
        f"- **Date Range:** {df['created'].min()} to {df['created'].max()}\n")

  report_content.append("### Potential Compatibility Issues")
  report_content.append(f"{plugin_analysis}\n")

  report_content.append("### Top Plugins")
  report_content.append(f"#### VST\n\n{vst_table}\n")
  report_content.append(f"#### AU\n\n{au_table}\n")

  report_content.append("### Project Inventory (Top 50 Recently Modified)")
  report_content.append(f"{inventory_table}\n")

  report_content.append("### Graphs")
  report_content.append(
      "#### Ableton Version\n![ableton_version](outputs/plots/ableton_version.png)\n"
  )
  report_content.append(
      "#### Creation Year\n![creation_year](outputs/plots/creation_year.png)\n"
  )
  report_content.append(
      "#### Last Modified Year\n![last_modified_year](outputs/plots/last_modified_year.png)\n"
  )
  report_content.append(
      "#### Track Types\n![tracks_dist](outputs/plots/tracks_dist.png)\n")
  report_content.append(
      "#### Device Types (Top 20)\n![device_types](outputs/plots/device_types.png)\n"
  )
  report_content.append(
      "#### File Size\n![filesize_dist](outputs/plots/filesize_dist.png)\n")
  report_content.append(
      "#### Tempo Distribution\n![tempo](outputs/plots/tempo_dist.png)\n")
  report_content.append(
      "#### Top VSTs\n![top_vst](outputs/plots/top_vst.png)\n")
  report_content.append("#### Top AUs\n![top_au](outputs/plots/top_au.png)\n")

  full_report = "\n".join(report_content)
  write_report_file(full_report)


def write_report_file(report_content: str) -> None:
  """Writes the generated report to REPORT.md."""
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
