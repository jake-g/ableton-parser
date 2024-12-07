"""Library for Parsing Ableton Live projects."""

from collections import Counter, defaultdict
import datetime
import gzip
import json
import os
import pickle
import plistlib
import sys
import time
from typing import Any, Callable, Dict, List, Tuple
import xml.etree.ElementTree as ET
import pandas as pd


# Constants
PROJECT_DIR = './'
CACHE_DIR = 'logs/'
CACHE_INFO_FILE = 'project_info'
SKIP_FOLDERS = [
    'Backup',
    'old',
    'Samples',
    'Ableton Project Info',
    '.stfolder',
    '.stversions',
    '.ipynb_checkpoints',
    '.git',
    'z__templates'
]
COUNTER_JSON = os.path.join(CACHE_DIR, 'counters.json')
PROJECT_TSV = os.path.join('projects.tsv')
PYTHON_VERSION = sys.version


class ALSNode:
  """Base class for parsing nodes in Ableton Live project files."""

  value_fields = {}

  def __init__(self, elem: ET.Element):
    self.elem = elem
    for key, field_spec in self.value_fields.items():
      selector, ivar, vtype = self._parse_field_spec(key, field_spec)
      val = self._value_for_subtag(selector, vtype)
      self.__dict__[ivar] = val

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

  def _value_for_subtag(
      self, selector: str, vtype: Callable[[str], Any] = None
  ) -> Any:
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

  def _guess_type_for_value(self, v: str) -> Callable[[str], Any] | None:
    """Infer the data type of a string value."""
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
    self.events = [
        (int(e.get('Time')), typefunc(e.get('Value')))
        for e in elem.findall('ArrangerAutomation/Events/*')
    ]


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
    self.sec_time = float(elem.get('SecTime'))
    self.beat_time = float(elem.get('BeatTime'))


class ALSMidiNote:
  """MIDI note in an Ableton Live clip."""

  def __init__(self, key: int | None, elem: ET.Element):
    self.time = float(elem.get('Time'))
    self.key = key
    self.duration = float(elem.get('Duration'))
    self.velocity = float(elem.get('Velocity'))
    self.off_velocity = int(elem.get('OffVelocity'))
    self.is_enabled = elem.get('IsEnabled') == 'true'


class LiveSetMidiClipData(ALSNode):
  """Data for a MIDI clip in an Ableton Live set."""

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    self.name = self._value_for_subtag('Name')
    self.annotation = self._value_for_subtag('Annotation')
    self.launch_mode = self._value_for_subtag('LaunchMode', int)
    self.current_start = self._value_for_subtag('CurrentStart', float)
    self.current_end = self._value_for_subtag('CurrentEnd', float)
    self.loop_start = self._value_for_subtag('Loop/LoopStart', float)
    self.loop_end = self._value_for_subtag('Loop/LoopEnd', float)
    self.loop_start_relative = self._value_for_subtag(
        'Loop/LoopStartRelative', float
    )

    self.warpmarkers = [
        ALSWarpMarker(e) for e in elem.findall('WarpMarkers/WarpMarker')
    ]
    self.length = (
        (self.current_end - self.current_start)
        if self.current_start and self.current_end
        else None
    )
    self.loop_on = self._bool_value_for_subtag('Loop/LoopOn')
    self.loop_length = (
        (self.loop_end - self.loop_start)
        if self.loop_start and self.loop_end
        else None
    )

    self.notes = []
    for ktrk in elem.findall('Notes/KeyTracks/KeyTrack'):
      midi_key_element = ktrk.find('MidiKey')
      note = (
          int(midi_key_element.get('Value'))
          if midi_key_element is not None
          else None
      )
      self.notes.extend([
          ALSMidiNote(note, mne) for mne in ktrk.findall('Notes/MidiNoteEvent')
      ])
    self.notes.sort(key=lambda mn: mn.time)


class LiveSetAuPluginPresetData:
  """Preset data for an AU plugin in Ableton Live."""

  def __init__(self, text: str):
    self.text = self._decode_hex_string(text)
    self.plist = plistlib.loads(bytes(self.text, 'utf-8'))
    self.name = self.plist.get('name')

  def _decode_hex_string(self, string: str) -> str:
    """Decode a hex string, ignoring non-hex characters."""
    hex_chars = ''.join(c for c in string.lower() if c in '0123456789abcdef')
    return bytes.fromhex(hex_chars).decode('utf-8')


class LiveSetDeviceData(ALSNode):
  """Data for a device in an Ableton Live set."""

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    self.device_type = elem.tag
    buffer_element = elem.find('PluginDesc/AuPluginInfo/Preset/AuPreset/Buffer')
    self.au_preset_buffer = (
        LiveSetAuPluginPresetData(buffer_element.text)
        if buffer_element is not None and buffer_element.text
        else None
    )
    self.au_preset_name = (
        self.au_preset_buffer.name if self.au_preset_buffer else None
    )

    name_element = elem.find('PluginDesc/AuPluginInfo/Name')
    self.preset_name = (
        self._value_for_subtag('UserName')
        or (name_element.get('Value') if name_element is not None else None)
        or self._value_for_subtag('PluginDesc/VstPluginInfo/PlugName')
        or ''
    )
    self.name = f'{self.device_type}: {self.preset_name}'


class LiveSetTrackData(ALSNode):
  """Data for a track in an Ableton Live set."""

  value_fields = {'Name': None}

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    self.track_type = elem.tag
    devices_path = 'DeviceChain/DeviceChain/Devices'
    self.devices = (
        [LiveSetDeviceData(c) for c in elem.findall(f'.//{devices_path}/*')]
        if elem.findall(f'.//{devices_path}/*')
        else []
    )

    mixer_element = elem.find('DeviceChain/Mixer')
    self.mixer = (
        ALSTrackMixer(mixer_element) if mixer_element is not None else None
    )
    clip_slot_list_element = elem.find('DeviceChain/MainSequencer/ClipSlotList')
    self.clip_slots = (
        clip_slot_list_element.findall('ClipSlot')
        if clip_slot_list_element is not None
        else []
    )
    self.midi_clips = []
    if clip_slot_list_element is not None:
      for c in clip_slot_list_element.findall('.//MidiClip'):
        self.midi_clips.append(LiveSetMidiClipData(c))


class LiveSetData:
  """Data extracted from an Ableton Live project file (.als)."""

  def __init__(self, path: str):
    self.etree = ET.parse(gzip.GzipFile(path))
    self.ableton_version = self.etree.getroot().get('MinorVersion')
    self.live_set = self.etree.getroot().find('LiveSet')
    self.tracks = [
        LiveSetTrackData(c) for c in self.live_set.findall('Tracks/*')
    ]
    # Works up thru ableton 11.
    master_track_element = self.live_set.find('MasterTrack')
    if master_track_element is not None:
      self.master_track = LiveSetTrackData(master_track_element)
    # Possible fix for finding Master in ableton 12+
    else:
      self.master_track = (
          self.tracks[-1]
          if self.tracks and self.tracks[-1].track_type == 'MainTrack'
          else None
      )

    self.file_size_mb = os.path.getsize(path) / (1024 * 1024)  # Convert to MB
    self.creation_time = datetime.datetime.fromtimestamp(os.path.getctime(path))
    self.modified_time = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    self.num_tracks = len(self.tracks) + (1 if self.master_track else 0)

  def time_signatures(self) -> List[Tuple[int, Tuple[int, int]]]:
    """Extract the time signatures defined in the project."""
    if self.master_track and self.master_track.mixer:
      return [
          (max(t, 0), self._decode_time_signature(enc))
          for t, enc in self.master_track.mixer.params['TimeSignature'].events
      ]
    else:
      return []

  def _decode_time_signature(self, encoded: int) -> Tuple[int, int]:
    """Decode an Ableton-encoded time signature to (numerator, denominator)."""
    return (encoded % 99 + 1, 1 << (encoded // 99))


def parse_als_info(
    path: str, include_midi_clips: bool = False
) -> Dict[str, Any]:
  """Extracts project information from an Ableton Live file (.als)."""

  lsd = LiveSetData(path)
  name, ext = os.path.splitext(path)
  assert ext == '.als', f'Expected .als file, got {ext}'

  project = {
      'path': path,
      'name': os.path.basename(name),
      'ableton_version_full': lsd.ableton_version,
      'tracks': [],
      'file_size_mb': round(lsd.file_size_mb, 2),
      'created': lsd.creation_time.strftime('%Y-%m-%d %H:%M:%S'),
      'modified': lsd.modified_time.strftime('%Y-%m-%d %H:%M:%S'),
      'num_tracks': lsd.num_tracks,
  }

  all_tracks = lsd.tracks
  if lsd.master_track and lsd.master_track.track_type == 'MasterTrack':
    all_tracks.append(lsd.master_track)

  counters = defaultdict(Counter)
  # Counters with one entry for project, used when merging all counters
  counters['ableton_version'][lsd.ableton_version.split('.')[0]] += 1
  counters['creation_year'][str(int(lsd.creation_time.year))] += 1
  counters['last_modified_year'][str(int(lsd.modified_time.year))] += 1

  for i, track_data in enumerate(all_tracks):
    i += 1
    if not track_data:
      print(f'  SKIPPING {track_data} track {i}')
      counters['warning_skipped_track'] += 1
      continue

    track_info = {
        'index': i,
        'type': track_data.track_type,
    }
    counters['track_types'][track_data.track_type] += 1
    track_info['devices'] = []
    for dev in track_data.devices:
      track_info['devices'].append(
          {'type': dev.device_type, 'preset': dev.preset_name}
      )
      counters['device_types'][dev.device_type] += 1
      if dev.device_type == 'PluginDevice':
        counters['plugins_vst'][dev.preset_name] += 1
      elif dev.device_type == 'AuPluginDevice':
        counters['plugins_au'][dev.preset_name] += 1

    # TODO parse AudioClips Groups need to add LiveSetMidiClipData
    # Currently midi clips not used for anything so not included by default
    if include_midi_clips:
      track_info['midi_clips'] = []
      for clip in track_data.midi_clips:
        track_info['midi_clips'].append({
            'name': clip.name,
            'length': clip.length,
            'is_loop': clip.loop_on,
        })
        counters['midi_clip_is_loop'][clip.loop_on] += 1

    project['tracks'].append(track_info)

  if not project['tracks']:
    print(f"WARNING: No tracks found in project: {project['name']}")
    counters['warning_no_tracks'] += 1
  project['counters'] = dict(counters)

  return project


def save_dict_as_json(
    json_path: str, data: Dict[str, Any], indent: int = 4, 
    sort: bool = True, verbose: bool = True
):
  """Saves a dictionary to a JSON file."""
  if verbose:
    print(f'Saving json: {json_path}.')
  with open(json_path, 'w') as f:
    json.dump(data, f, indent=indent, sort_keys=sort)


def load_dict_from_json(json_path: str, verbose: bool = True) -> Dict[str, Any]:
  """Loads a dictionary from a JSON file."""
  if verbose:
    print(f'Loading json: {json_path}.')
  with open(json_path, 'r') as f:
    return json.load(f)


def print_dict(data: Dict[str, Any]) -> None:
  """Pretty-prints a dictionary as formatted JSON."""
  print(json.dumps(data, indent=4, sort_keys=True))


def create_project_df(
    project_info: Dict[str, Any], tsv_path: str = None
) -> pd.DataFrame:
  """Creates a Pandas DataFrame summarizing project information."""

  def _format_counters(counters):
    """Helper to format counter dictionaries."""
    formatted = {}
    for name, counter in counters.items():
      if counter and (
          len(counter) > 1
          or (len(counter) == 1 and list(counter.values())[0] != 0)
      ):
        formatted[name] = ', '.join(counter.keys())
    return formatted

  skip_keys = ['counters', 'tracks']
  rows = []
  for project in project_info.values():
    row = {key: project.get(key) for key in project if key not in skip_keys}
    row.update(_format_counters(project.get('counters', {})))
    rows.append(row)

  df = pd.DataFrame(rows).set_index('name')
  print(f'Created DataFrame with shape {df.shape}')
  if tsv_path:
    df.to_csv(tsv_path, sep='\t')
  return df


def load_project_df_from_tsv(tsv_path: str) -> pd.DataFrame:
  """Loads a Pandas DataFrame from a TSV file."""
  print(f'Loading tsv: {tsv_path}.')
  return pd.read_csv(tsv_path, sep='\t', index_col=0)


def save_counters(
    project_info: Dict[str, Any], display: bool = True, save_path: str = None
) -> Dict[str, Counter[Any]]:
  """Merges counters from multiple projects into a single set of counters."""
  counters = defaultdict(Counter)
  for project in project_info.values():
    for counter_name, counter in project['counters'].items():
      counters[counter_name].update(counter)

  # Convert Counters to regular dictionaries for JSON serialization
  counters = {name: dict(counter) for name, counter in counters.items()}
  if display:
    for name, counter in counters.items():
      print(f"\n{name.replace('_', ' ').title()}:")
      print_dict(counter)
  if save_path:
    save_dict_as_json(save_path, counters)
  return counters


def save_info(cache_dir: str, info_dict: Dict[str, Any], prefix: str) -> str:
  """Save project information to a cache file."""
  timestamp = int(time.time())
  save_date = datetime.datetime.fromtimestamp(timestamp)
  save_path = os.path.join(cache_dir, f'{prefix}.{timestamp}')
  print(f'Saving {prefix} from {save_date}.')
  with open(save_path, 'wb') as handle:
    pickle.dump(info_dict, handle, protocol=pickle.HIGHEST_PROTOCOL)
  sys.stdout.flush()
  return save_path


def load_info(
    cache_dir: str = CACHE_DIR,
    prefix: str = CACHE_INFO_FILE,
    cache_file: str = '',
    load_most_recent: bool = True,
) -> Dict[str, Any]:
  """Load project information from a cache file."""
  cache = sorted([f for f in os.listdir(cache_dir) if prefix in f])
  if not cache:
    print(f'  No cache files found matching prefix: {prefix}')
    return {}

  if load_most_recent:
    cache_file = cache[-1]
  elif cache_file not in cache:
    print(f'WARNING: Cache: {cache_file} not found. Loading most recent.')
    cache_file = cache[-1]

  cache_path = os.path.join(cache_dir, cache_file)
  timestamp = int(cache_path.split('.')[-1])
  cache_date = datetime.datetime.fromtimestamp(timestamp)
  t0 = time.time()
  print(f'Loading {prefix} from {cache_date}.')
  with open(cache_path, 'rb') as handle:
    info_dict = pickle.load(handle)
  print(f'Loaded {len(info_dict)} {prefix} in {time.time() - t0:.2f} seconds.')
  return info_dict


def load_projects_in_dir(
    project_dir: str, skip_folders: List[str] = tuple(SKIP_FOLDERS),
    save_info_json: bool = False, verbose: bool = False
) -> Dict[str, Any]:
  """Load information for all .als projects in a directory."""
  project_ext = '.als'
  project_info = {}
  t0 = time.time()
  error_count = 0
  print(f'Loading projects in {project_dir}.')
  for dirpath, _, filenames in os.walk(project_dir):
    if any(f in dirpath for f in skip_folders):
      continue
    for filename in filenames:
      key, ext = os.path.splitext(filename)
      if ext == project_ext and not key.startswith('.'):
        full_filename = os.path.join(dirpath, filename)
        print(f' READING: {key}')
        try:
          info = parse_als_info(full_filename)
          counters = info.get('counters', {})
          if save_info_json and counters:
            json_info_file = full_filename.replace(project_ext, '.json')
            save_dict_as_json(json_info_file, counters, sort=False, verbose=verbose)
          project_info[key] = info
        except (ET.ParseError, TypeError, ValueError) as e:
          project_info[key] = {'error': e, 'path': full_filename}
          error_count += 1
          print(f'  ERROR: {e}')
        sys.stdout.flush()

  elapsed = time.time() - t0
  print(
      f'Loaded {len(project_info)} projects with '
      f'{error_count} errors in {elapsed:.2f} seconds.'
  )

  return project_info


def run_parser(
    project_dir: str = PROJECT_DIR,
    skip_dirs: List[str] = tuple(SKIP_FOLDERS),
    cache_dir: str = CACHE_DIR,
    cache_info_file: str = CACHE_INFO_FILE,
    save_project_json: bool = True
) -> Tuple[Dict[str, Any], Dict[str, Any], pd.DataFrame]:
  """Main entry point for parsing Ableton Live projects."""
  print(
      f'Project path: {project_dir}\n'
      f'Found Dirs: {sorted(os.listdir(project_dir))}\n'
      f'Skipping Dirs containing: {sorted(skip_dirs)}'
  )

  project_info = load_projects_in_dir(project_dir, save_info_json=save_project_json)
  print(f'Caching project info to {cache_dir}')
  save_info(cache_dir, project_info, prefix=cache_info_file)
  project_df = create_project_df(project_info, tsv_path=PROJECT_TSV)
  project_counters = save_counters(
      project_info, display=True, save_path=COUNTER_JSON
  )

  return project_info, project_counters, project_df


if __name__ == '__main__':
  info, counters, df = run_parser(project_dir=os.getcwd())
