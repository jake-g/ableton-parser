"""Library for Parsing Ableton Live projects."""

import datetime
import gzip
import os
import pickle
import plistlib
import sys
import time
from typing import Any, Callable, Dict, List, Tuple
import xml.etree.ElementTree as ET

# Constants
PROJECT_DIR = './'
CACHE_DIR = 'logs/'
CACHE_INFO_FILE = 'project_info'
CACHE_ERROR_FILE = 'project_errors'
SKIP_FOLDERS = [
    'Backup',
    'old',
    'Samples',
    'Ableton Project Info',
    '.stfolder',
    '.stversions',
    '.ipynb_checkpoints',
    '.git',
]
PYTHON_VERSION = sys.version

ProjectMap = Dict[str, Any]

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
    self.devices = [LiveSetDeviceData(c) for c in elem.find(devices_path)]
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
    self.live_set = self.etree.getroot().find('LiveSet')
    self.tracks = [LiveSetTrackData(c) for c in self.live_set.find('Tracks')]
    master_track_element = self.live_set.find('MasterTrack')
    self.master_track = (
        LiveSetTrackData(master_track_element)
        if master_track_element is not None
        else None
    )

  def time_signatures(self) -> List[Tuple[int, Tuple[int, int]]]:
    """Extract the time signatures defined in the project."""
    return [
        (max(t, 0), self._decode_time_signature(enc))
        for t, enc in self.master_track.mixer.params['TimeSignature'].events
    ]

  def _decode_time_signature(self, encoded: int) -> Tuple[int, int]:
    """Decode an Ableton-encoded time signature to (numerator, denominator)."""
    return (encoded % 99 + 1, 1 << (encoded // 99))


def parse_als_info(path: str) -> Dict[str, Any]:
  """Extract project information from an Ableton Live file (.als)."""
  lsd = LiveSetData(path)
  name, ext = os.path.splitext(path)
  assert ext == '.als', f'Expected .als file, got {ext}'
  info = {
      'path': path,
      'name': os.path.basename(name),
      'project': os.path.dirname(name).split('/')[-1].replace(' Project', ''),
      'tracks': [],
  }
  all_tracks = lsd.tracks + [lsd.master_track]
  for i, track_data in enumerate(all_tracks):
    i += 1
    if not track_data:
      print(f'  SKIPPING {track_data} track {i}')
      continue
    track_info = {
        'index': i,
        'type': track_data.track_type,
        'devices': [],
        'clips': [],
    }
    for dev in track_data.devices:
      track_info['devices'].append(
          {'type': dev.device_type, 'preset': dev.preset_name}
      )
    for clip in track_data.midi_clips:
      track_info['clips'].append(
          {'name': clip.name, 'length': clip.length, 'is_loop': clip.loop_on}
      )
    info['tracks'].append(track_info)
    if track_data.mixer.params:
      print(' DEBUG: track has mixer params (likely older project)')
    if track_data.name:
      print(f' DEBUG: track has name (which is rare): {track_data.name}')

  return info


def save_info(cache_dir: str, info_dict: ProjectMap, prefix: str) -> str:
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
) -> ProjectMap:
  """Load project information from a cache file."""
  cache = sorted([f for f in os.listdir(cache_dir) if prefix in f])
  cache_file = (
      cache[-1] if (cache_file not in cache or load_most_recent) else cache_file
  )
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
    project_dir: str, skip_folders: List[str] = tuple(SKIP_FOLDERS)
) -> Tuple[ProjectMap, ProjectMap]:
  """Load information for all .als projects in a directory."""
  project_info = {}
  project_errors = {}
  t0 = time.time()
  print(f'Loading projects in {project_dir}.')
  for dirpath, _, filenames in os.walk(project_dir):
    if any(f in dirpath for f in skip_folders):
      continue
    for filename in filenames:
      key, ext = os.path.splitext(filename)
      if ext == '.als' and not key.startswith('.'):
        full_filename = os.path.join(dirpath, filename)
        print(f' READING: {key}')
        try:
          project_info[key] = parse_als_info(full_filename)
        except (ET.ParseError, TypeError, ValueError) as e:
          project_errors[key] = e
          print(f'  ERROR: {e}')
        sys.stdout.flush()

  elapsed = time.time() - t0
  print(
      f'Loaded {len(project_info)} projects with '
      f'{len(project_errors)} errors in {elapsed:.2f} seconds.'
  )
  return project_info, project_errors


def run_parser(
    project_dir: str = PROJECT_DIR,
    skip_dirs: List[str] = tuple(SKIP_FOLDERS),
    cache_dir: str = CACHE_DIR,
    cache_info_file: str = CACHE_INFO_FILE,
    cache_error_file: str = CACHE_ERROR_FILE,
) -> Tuple[ProjectMap, ProjectMap]:
  """Main entry point for parsing Ableton Live projects."""
  print(
      f'Project path: {project_dir}\n'
      f'Found Dirs: {sorted(os.listdir(project_dir))}\n'
      f'Skipping Dirs containing: {sorted(skip_dirs)}'
  )

  project_info, project_errors = load_projects_in_dir(project_dir)
  print(f'Caching project info to {cache_dir}')
  if project_info:
    save_info(cache_dir, project_info, prefix=cache_info_file)
  if project_errors:
    save_info(cache_dir, project_errors, prefix=cache_error_file)
  
  return project_info, project_errors

if __name__ == '__main__':
  info, errors = run_parser(project_dir=os.getcwd())
