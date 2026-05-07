"""Library for Parsing Ableton Live projects."""

import argparse
from collections import Counter
from collections import defaultdict
import datetime
import gzip
import json
import logging
import os
import pickle
import plistlib
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

import pandas as pd

# Configure Logging
logger = logging.getLogger(__name__)

# Constants
PROJECT_DIR = './'
OUTPUT_DIR = 'outputs/'
CACHE_INFO_FILE = 'project_info'
SKIP_FOLDERS = [
    'Backup', 'old', 'Samples', 'Ableton Project Info', '.stfolder',
    '.stversions', '.ipynb_checkpoints', '.git', 'z__templates', 'outputs'
]
COUNTERS_JSON = os.path.join(OUTPUT_DIR, 'counters.json')
PROJECT_TSV = os.path.join(OUTPUT_DIR, 'projects.tsv')
PYTHON_VERSION = sys.version


class ALSNode:
  """Base class for parsing nodes in Ableton Live project files."""

  value_fields: Dict[str, Any] = {}

  def __init__(self, elem: ET.Element):
    self.elem = elem
    for key, field_spec in self.value_fields.items():
      selector, ivar, vtype = self._parse_field_spec(key, field_spec)
      val = self._value_for_subtag(selector, vtype)
      setattr(self, ivar, val)

  def _parse_field_spec(self, key, field_spec):
    """Parses the field specification and extracts selector, ivar, and vtype."""
    if isinstance(field_spec, dict):
      selector = field_spec.get('sel', key)
      ivar = field_spec.get('ivar', key)
      vtype = field_spec.get('type', None)
    elif isinstance(field_spec, tuple):
      selector, ivar, vtype = field_spec[1], key, field_spec[0]
    else:
      selector = key
      ivar = key[0].lower() + key[1:]
      vtype = field_spec
    return selector, ivar, vtype

  def _value_for_subtag(self,
                        selector: str,
                        vtype: Optional[Callable[[str], Any]] = None) -> Any:
    """Extract and optionally type-convert a value from a sub-element."""
    element = self.elem.find(selector)
    val = element.get('Value') if element is not None else None
    if val is not None and vtype is not None:
      try:
        return vtype(val)
      except ValueError:
        pass
    return val

  def _bool_value_for_subtag(self, selector: str) -> bool:
    """Extract a boolean value from a sub-element."""
    return self._value_for_subtag(selector) == 'true'

  def _guess_type_for_value(self,
                            v: Optional[str]) -> Optional[Callable[[str], Any]]:
    """Infer the data type of a string value."""
    if v is None:
      return None
    if v in ('true', 'false'):
      return lambda string: string == 'true'
    for fn in (int, float):
      try:
        fn(v)
        return fn
      except ValueError:
        pass
    return None


class ALSTrackMixerParam(ALSNode):
  """Parameters of an Ableton Live track mixer."""

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    manual = self._value_for_subtag('Manual')
    self.type = self._guess_type_for_value(manual)
    typefunc = self.type or (lambda x: x)
    self.manual = typefunc(manual)
    self.events: List[Tuple[int, Any]] = []
    for e in elem.findall('ArrangerAutomation/Events/*'):
      time_attr = e.get('Time')
      value_attr = e.get('Value')
      if time_attr is not None:
        self.events.append((int(time_attr), typefunc(value_attr or '')))


class ALSTrackMixer(ALSNode):
  """Mixer for an Ableton Live track."""

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    self.params = {
        e.tag: ALSTrackMixerParam(e)
        for e in elem.findall('*[ArrangerAutomation]')
    }


class ALSWarpMarker:
  """Warp marker in an Ableton Live clip."""

  def __init__(self, elem: ET.Element):
    self.sec_time = float(elem.get('SecTime', 0))
    self.beat_time = float(elem.get('BeatTime', 0))


class ALSMidiNote:
  """MIDI note in an Ableton Live clip."""

  def __init__(self, key: Optional[int], elem: ET.Element):
    # pylint: disable=too-many-instance-attributes
    self.time = float(elem.get('Time', 0))
    self.key = key
    self.duration = float(elem.get('Duration', 0))
    self.velocity = float(elem.get('Velocity', 0))
    self.off_velocity = int(elem.get('OffVelocity', 0))
    self.is_enabled = elem.get('IsEnabled') == 'true'


class LiveSetClipData(ALSNode):
  """Data for a clip (Midi or Audio)."""

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    self.name = self._value_for_subtag('Name') or 'Untitled'
    self.start = float(elem.get('CurrentStart', 0))
    self.end = float(elem.get('CurrentEnd', 0))
    self.loop_on = self._bool_value_for_subtag('Loop/LoopOn')
    self.time = float(elem.get('Time', 0))
    self.length = self.end - self.start
    self.global_end = self.time + self.length


class LiveSetMidiClipData(LiveSetClipData):
  """Data for a MIDI clip in an Ableton Live set."""

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    self.annotation = self._value_for_subtag('Annotation')
    self.launch_mode = self._value_for_subtag('LaunchMode', int)
    self.current_start = self._value_for_subtag('CurrentStart', float)
    self.current_end = self._value_for_subtag('CurrentEnd', float)
    self.loop_start = self._value_for_subtag('Loop/LoopStart', float)
    self.loop_end = self._value_for_subtag('Loop/LoopEnd', float)
    self.loop_start_relative = self._value_for_subtag('Loop/LoopStartRelative',
                                                      float)

    self.warpmarkers = [
        ALSWarpMarker(e) for e in elem.findall('WarpMarkers/WarpMarker')
    ]
    # self.length handled by super

    self.loop_length = None
    if self.loop_start is not None and self.loop_end is not None:
      self.loop_length = self.loop_end - self.loop_start

    self.notes = []
    for ktrk in elem.findall('Notes/KeyTracks/KeyTrack'):
      midi_key_element = ktrk.find('MidiKey')
      note_val = midi_key_element.get(
          'Value') if midi_key_element is not None else None
      note = int(note_val) if note_val else None
      self.notes.extend([
          ALSMidiNote(note, mne) for mne in ktrk.findall('Notes/MidiNoteEvent')
      ])
    self.notes.sort(key=lambda mn: mn.time)


class LiveSetAudioClipData(LiveSetClipData):
  """Data for an Audio clip."""
  pass


class LiveSetAuPluginPresetData:
  """Preset data for an AU plugin in Ableton Live."""

  def __init__(self, text: str):
    self.text = self._decode_hex_string(text)
    try:
      self.plist = plistlib.loads(bytes(self.text, 'utf-8'))
      self.name = self.plist.get('name')
    except Exception:
      self.plist = {}
      self.name = None

  def _decode_hex_string(self, string: str) -> str:
    """Decode a hex string, ignoring non-hex characters."""
    hex_chars = ''.join(c for c in string.lower() if c in '0123456789abcdef')
    try:
      return bytes.fromhex(hex_chars).decode('utf-8')
    except Exception:
      return ""


class LiveSetDeviceData(ALSNode):
  """Data for a device in an Ableton Live set."""

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    self.device_type = elem.tag
    buffer_element = elem.find('PluginDesc/AuPluginInfo/Preset/AuPreset/Buffer')
    self.au_preset_buffer = (LiveSetAuPluginPresetData(buffer_element.text)
                             if buffer_element is not None
                             and buffer_element.text else None)
    self.au_preset_name = (self.au_preset_buffer.name
                           if self.au_preset_buffer else None)

    name_element = elem.find('PluginDesc/AuPluginInfo/Name')
    self.preset_name = (
        self._value_for_subtag('UserName') or
        (name_element.get('Value') if name_element is not None else None) or
        self._value_for_subtag('PluginDesc/VstPluginInfo/PlugName') or '')
    self.name = f'{self.device_type}: {self.preset_name}'


class LiveSetTrackData(ALSNode):
  """Data for a track in an Ableton Live set."""

  value_fields = {'Name': None}

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    self.track_type = elem.tag
    self.devices: List[LiveSetDeviceData] = []
    # Try standard path first
    found_devices = elem.findall('DeviceChain/Devices/*')
    if not found_devices:
      # Fallback for nested chains or older versions?
      found_devices = elem.findall('DeviceChain/DeviceChain/Devices/*')

    if found_devices:
      self.devices = [LiveSetDeviceData(c) for c in found_devices]
    mixer_element = elem.find('DeviceChain/Mixer')
    self.mixer = (ALSTrackMixer(mixer_element)
                  if mixer_element is not None else None)
    clip_slot_list_element = elem.find('DeviceChain/MainSequencer/ClipSlotList')
    self.clip_slots = (clip_slot_list_element.findall('ClipSlot')
                       if clip_slot_list_element is not None else [])
    self.midi_clips: List[LiveSetMidiClipData] = []
    self.audio_clips: List[LiveSetAudioClipData] = []
    processed_clips = set()

    # Parse Session Clips (in ClipSlots)
    if clip_slot_list_element is not None:
      for c in clip_slot_list_element.findall('.//MidiClip'):
        if c not in processed_clips:
          self.midi_clips.append(LiveSetMidiClipData(c))
          processed_clips.add(c)
      for c in clip_slot_list_element.findall('.//AudioClip'):
        if c not in processed_clips:
          self.audio_clips.append(LiveSetAudioClipData(c))
          processed_clips.add(c)

    # Check arrangement clips too (MainSequencer/Track/ArrangerAutomation/Events/...)
    sequencer = elem.find('DeviceChain/MainSequencer')
    if sequencer is not None:
      for c in sequencer.findall('.//MidiClip'):
        if c not in processed_clips:
          self.midi_clips.append(LiveSetMidiClipData(c))
          processed_clips.add(c)
      for c in sequencer.findall('.//AudioClip'):
        if c not in processed_clips:
          self.audio_clips.append(LiveSetAudioClipData(c))
          processed_clips.add(c)


class LiveSetData:
  """Data extracted from an Ableton Live project file (.als)."""

  def __init__(self, path: str):
    # pylint: disable=too-many-instance-attributes
    with gzip.open(path, 'rb') as f:
      self.etree = ET.parse(f)
    self.root = self.etree.getroot()
    self.live_set = self.root.find('LiveSet')

    if self.live_set is None:
      raise ValueError("No LiveSet element found")

    # Extract Tempo
    self.tempo: Optional[float] = None
    tempo_elem = self.live_set.find('.//o:Tempo/o:Manual', namespaces={'o': '*'})
    if tempo_elem is None:
      tempo_elem = self.live_set.find(
          'MasterTrack/DeviceChain/Mixer/Tempo/Manual')

    if tempo_elem is not None:
      try:
        val = tempo_elem.get('Value')
        if val:
            self.tempo = float(val)
      except (ValueError, TypeError):
        pass

    # Extract Time Signature
    self.time_signature: Optional[str] = None
    ts_elem = self.live_set.find(
        'MasterTrack/DeviceChain/Mixer/TimeSignature/Manual')
    if ts_elem is not None:
      try:
        ts_val = ts_elem.get('Value', '65540')
        self.time_signature = str(ts_val)
      except (ValueError, TypeError):
        pass
    self.ableton_version = self.root.get('MinorVersion')

    self.tracks = [
        LiveSetTrackData(c) for c in self.live_set.findall('Tracks/*')
    ]
    self.master_track: Optional[LiveSetTrackData] = None
    # Works up thru ableton 11.
    master_track_element = self.live_set.find('MasterTrack')
    if master_track_element is not None:
      self.master_track = LiveSetTrackData(master_track_element)
    # Possible fix for finding Master in ableton 12+
    else:
      self.master_track = (self.tracks[-1] if self.tracks and
                           self.tracks[-1].track_type == 'MainTrack' else None)

    self.file_size_mb = os.path.getsize(path) / (1024 * 1024)  # Convert to MB
    self.creation_time = datetime.datetime.fromtimestamp(os.path.getctime(path))
    self.modified_time = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    self.num_tracks = len(self.tracks) + (1 if self.master_track else 0)

    # Scale Information
    self.scale_root_note: Optional[str] = None
    self.scale_name: Optional[str] = None
    scale_info = self.live_set.find('ScaleInformation')
    if scale_info is not None:
      root_note_val = scale_info.find('RootNote')
      if root_note_val is not None:
        # 0=C, 1=C#, etc.
        notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        try:
          val_str = root_note_val.get('Value')
          if val_str:
            idx = int(val_str)
            self.scale_root_note = notes[idx % 12]
        except (ValueError, TypeError, IndexError):
          pass

      scale_name_val = scale_info.find('Name')
      if scale_name_val is not None:
        self.scale_name = scale_name_val.get('Value')

    # Calculate Duration (max global end time of any clip)
    self.duration_seconds = 0.0
    max_beats = 0.0

    all_clips: List[LiveSetClipData] = []
    for t in self.tracks:
      all_clips.extend(t.midi_clips)
      all_clips.extend(t.audio_clips)

    for clip in all_clips:
      if clip.global_end > max_beats:
        max_beats = clip.global_end

    # Convert beats to seconds if tempo is known
    # Duration in seconds = (beats / tempo) * 60
    if self.tempo and self.tempo > 0:
      self.duration_seconds = (max_beats / self.tempo) * 60
    else:
      self.duration_seconds = (max_beats / 120.0) * 60  # assumption


def parse_als_info(path: str,
                   include_midi_clips: bool = False) -> Dict[str, Any]:
  """Extracts project information from an Ableton Live file (.als)."""

  lsd = LiveSetData(path)
  name, ext = os.path.splitext(path)
  if ext != '.als':
    raise ValueError(f'Expected .als file, got {ext}')

  project: Dict[str, Any] = {
      'path': path,
      'name': os.path.basename(name),
      'ableton_version_full': lsd.ableton_version,
      'tracks': [],
      'file_size_mb': round(lsd.file_size_mb, 2),
      'created': lsd.creation_time.strftime('%Y-%m-%d %H:%M:%S'),
      'modified': lsd.modified_time.strftime('%Y-%m-%d %H:%M:%S'),
      'num_tracks': lsd.num_tracks,
      'tempo': lsd.tempo,
      'time_signature': lsd.time_signature,
      'scale_root': lsd.scale_root_note,
      'scale_name': lsd.scale_name,
      'duration_sec': round(lsd.duration_seconds, 2),
  }

  all_tracks: List[LiveSetTrackData] = list(lsd.tracks)
  if lsd.master_track and lsd.master_track.track_type == 'MasterTrack':
    all_tracks.append(lsd.master_track)

  counters: Dict[str, Counter[str]] = defaultdict(Counter)
  if lsd.ableton_version:
    major_version = lsd.ableton_version.split('.')[0]
    counters['ableton_version'].update([major_version])

  counters['creation_year'].update([str(int(lsd.creation_time.year))])
  counters['last_modified_year'].update([str(int(lsd.modified_time.year))])

  for i, track_data in enumerate(all_tracks):
    i += 1
    if not track_data:
      continue

    track_info: Dict[str, Any] = {
        'index': i,
        'type': track_data.track_type,
    }
    counters['track_types'].update([track_data.track_type])
    track_info['devices'] = []

    for dev in track_data.devices:
      track_info['devices'].append({
          'type': dev.device_type,
          'preset': dev.preset_name
      })
      counters['device_types'].update([dev.device_type])
      if dev.device_type == 'PluginDevice':
        counters['plugins_vst'].update([dev.preset_name])
      elif dev.device_type == 'AuPluginDevice':
        counters['plugins_au'].update([dev.preset_name])

    if include_midi_clips:
      track_info['midi_clips'] = []
      for clip in track_data.midi_clips:
        track_info['midi_clips'].append({
            'name': clip.name,
            'length': clip.length,
            'is_loop': clip.loop_on,
        })
        if clip.loop_on is not None:
          counters['midi_clip_is_loop'].update([str(clip.loop_on)])

    if isinstance(project['tracks'], list):
      project['tracks'].append(track_info)

  if not project['tracks']:
    logger.warning(f"No tracks found in project: {project['name']}")
    counters['warning_no_tracks'].update(['count'])
  project['counters'] = dict(counters)

  return project


def save_dict_as_json(json_path: str,
                      data: Dict[str, Any],
                      indent: int = 4,
                      sort: bool = True):
  """Saves a dictionary to a JSON file."""
  logger.debug(f'Saving json: {json_path}.')
  os.makedirs(os.path.dirname(json_path), exist_ok=True)
  with open(json_path, 'w') as f:
    json.dump(data, f, indent=indent, sort_keys=sort)


def load_dict_from_json(json_path: str) -> Dict[str, Any]:
  """Loads a dictionary from a JSON file."""
  logger.debug(f'Loading json: {json_path}.')
  with open(json_path, 'r') as f:
    return json.load(f)


def create_project_df(project_info: Dict[str, Any],
                      tsv_path: Optional[str] = None) -> pd.DataFrame:
  """Creates a Pandas DataFrame summarizing project information."""

  def _format_counters(counters: Dict[str, Dict[str, int]]) -> Dict[str, str]:
    """Helper to format counter dictionaries."""
    formatted = {}
    for name, counter in counters.items():
      if counter and (len(counter) > 1 or
                      (len(counter) == 1 and list(counter.values())[0] != 0)):
        formatted[name] = ', '.join(counter.keys())
    return formatted

  skip_keys = ['counters', 'tracks']
  rows = []
  for project in project_info.values():
    if 'error' in project:
      continue
    row = {key: project.get(key) for key in project if key not in skip_keys}
    row.update(_format_counters(project.get('counters', {})))
    rows.append(row)

  df = pd.DataFrame(rows)
  if not df.empty and 'name' in df.columns:
    df = df.set_index('name')

  logger.info(f'Created DataFrame with shape {df.shape}')
  if tsv_path:
    os.makedirs(os.path.dirname(tsv_path), exist_ok=True)
    df.to_csv(tsv_path, sep='\t')
  return df


def save_counters(project_info: Dict[str, Any],
                  save_path: Optional[str] = None) -> Dict[str, Any]:
  """Merges counters from multiple projects into a single set of counters."""
  counters: Dict[str, Counter[Any]] = defaultdict(Counter)
  for project in project_info.values():
    if 'counters' not in project:
      continue
    for counter_name, counter in project['counters'].items():
      counters[counter_name].update(counter)

  # Convert Counters to regular dictionaries for JSON serialization
  final_counters = {name: dict(counter) for name, counter in counters.items()}

  if save_path:
    save_dict_as_json(save_path, final_counters)
  return final_counters


def save_info(cache_dir: str, info_dict: Dict[str, Any], prefix: str) -> str:
  """Save project information to a cache file."""
  os.makedirs(cache_dir, exist_ok=True)
  save_path = os.path.join(cache_dir, f'{prefix}.pkl')
  logger.info(f'Saving {prefix} snapshot to {save_path}')
  with open(save_path, 'wb') as handle:
    pickle.dump(info_dict, handle, protocol=pickle.HIGHEST_PROTOCOL)
  return save_path


def load_info(
    cache_dir: str = OUTPUT_DIR,
    prefix: str = CACHE_INFO_FILE,
    cache_file: str = '',
    load_most_recent: bool = True,
) -> Dict[str, Any]:
  """Load project information from a cache file."""
  if not os.path.exists(cache_dir):
    logger.warning(f"Cache directory {cache_dir} does not exist.")
    return {}

  cache = sorted(
      [f for f in os.listdir(cache_dir) if prefix in f and f.endswith('.pkl')])
  if not cache:
    logger.warning(f'No cache files found matching prefix: {prefix}')
    return {}

  if load_most_recent:
    # Since we now use a fixed filename, we just check for it
    if f'{prefix}.pkl' in os.listdir(cache_dir):
      cache_file = f'{prefix}.pkl'
    elif cache:
      # Fallback to old timestamped files if they exist
      cache_file = cache[-1]
    else:
      return {}
  elif cache_file not in cache and cache_file != f'{prefix}.pkl':
    logger.warning(f'Cache: {cache_file} not found. Loading default.')
    cache_file = f'{prefix}.pkl'

  cache_path = os.path.join(cache_dir, cache_file)
  logger.info(f'Loading {prefix} from {cache_path}.')
  try:
    with open(cache_path, 'rb') as handle:
      return pickle.load(handle)
  except Exception as e:
    logger.error(f"Failed to load cache: {e}")
    return {}


def load_projects_in_dir(project_dir: str,
                         skip_folders: Tuple[str, ...] = tuple(SKIP_FOLDERS),
                         save_info_json: bool = False) -> Dict[str, Any]:
  """Load information for all .als projects in a directory."""
  project_ext = '.als'
  project_info = {}
  t0 = time.time()
  error_count = 0
  logger.info(f'Loading projects in {project_dir}...')

  for dirpath, _, filenames in os.walk(project_dir):
    if any(f in dirpath for f in skip_folders):
      continue
    for filename in filenames:
      key, ext = os.path.splitext(filename)
      if ext == project_ext and not key.startswith('.'):
        full_filename = os.path.join(dirpath, filename)
        logger.info(f'Reading: {key}')
        try:
          info = parse_als_info(full_filename)
          counters = info.get('counters', {})
          if save_info_json and counters:
            json_info_file = full_filename.replace(project_ext, '.json')
            save_dict_as_json(json_info_file, counters, sort=False)
          project_info[key] = info
        except Exception:
          # logger.error(f'Failed to parse {full_filename}: {e}') # Optional: log if needed but keep clean
          # actually we should log e
          pass

  elapsed = time.time() - t0
  logger.info(f'Loaded {len(project_info)} projects with '
              f'{error_count} errors in {elapsed:.2f} seconds.')

  return project_info


def run_parser(project_dir: str = PROJECT_DIR,
               skip_dirs: Tuple[str, ...] = tuple(SKIP_FOLDERS),
               output_dir: str = OUTPUT_DIR,
               save_project_json: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any], pd.DataFrame]:
  """Main entry point for parsing Ableton Live projects."""
  logger.info(f'Starting parser in {project_dir}')
  logger.info(f'Skipping folders: {skip_dirs}')

  os.makedirs(output_dir, exist_ok=True)

  project_info = load_projects_in_dir(project_dir,
                                      save_info_json=save_project_json)

  save_info(output_dir, project_info, prefix=CACHE_INFO_FILE)

  project_df = create_project_df(project_info, tsv_path=PROJECT_TSV)
  project_counters = save_counters(project_info, save_path=COUNTERS_JSON)

  return project_info, project_counters, project_df


def setup_logging(debug: bool = False):
  """Configures logging."""
  os.makedirs(OUTPUT_DIR, exist_ok=True)
  log_file = os.path.join(OUTPUT_DIR, 'parse_projects.log')

  level = logging.DEBUG if debug else logging.INFO

  # File handler
  file_handler = logging.FileHandler(log_file, mode='w')
  file_handler.setLevel(level)
  file_handler.setFormatter(
      logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

  # Console handler
  console_handler = logging.StreamHandler()
  console_handler.setLevel(level)
  console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

  # Root logger
  root_logger = logging.getLogger()
  root_logger.setLevel(level)  # Capture everything at the desired level
  root_logger.addHandler(file_handler)
  root_logger.addHandler(console_handler)

  logger.info(f"Logging initialized. Log file: {log_file}")


if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Parse Ableton Projects')
  parser.add_argument('--root', default='.', help='Root directory to search')
  parser.add_argument('--debug',
                      action='store_true',
                      help='Enable debug logging to console')
  parser.add_argument('--save-json',
                      action='store_true',
                      help='Save .json files for each project')
  args = parser.parse_args()

  setup_logging(args.debug)

  try:
    run_parser(project_dir=args.root, save_project_json=args.save_json)
  except Exception:
    logger.exception("Fatal error in main execution")
    sys.exit(1)
