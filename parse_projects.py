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
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import wave
import xml.etree.ElementTree as ET

import pandas as pd

# Configure Logging
logger = logging.getLogger(__name__)

# Constants
PROJECT_DIR = './'
OUTPUT_DIR = 'outputs/'
CACHE_INFO_FILE = 'project_info'
# NOTE: these are matched as whole path components, never as substrings.
# Substring matching silently drops any project whose path merely contains
# one of these words (e.g. 'old' matches 'folder', 'Gold', 'Bold').
SKIP_FOLDERS = [
    'Backup', 'old', 'Samples', 'Ableton Project Info', '.stfolder',
    '.stversions', '.ipynb_checkpoints', '.git', 'z__templates', 'outputs'
]
COUNTERS_JSON = os.path.join(OUTPUT_DIR, 'counters.json')
PROJECT_TSV = os.path.join(OUTPUT_DIR, 'projects.tsv')
SAMPLES_TSV = os.path.join(OUTPUT_DIR, 'samples.tsv')
PYTHON_VERSION = sys.version

# Live's built-in instrument device tags. Anything else that is not a
# plugin host is treated as an audio effect.
INSTRUMENT_DEVICE_TAGS = frozenset({
    'OriginalSimpler', 'MultiSampler', 'Operator', 'InstrumentVector',
    'InstrumentImpulse', 'DrumGroupDevice', 'InstrumentGroupDevice',
    'UltraAnalog', 'Collision', 'Tension', 'Electric', 'InstrumentMeld',
    'Drift', 'BassDevice', 'Sampler', 'Simpler',
})
PLUGIN_DEVICE_TAGS = frozenset({'PluginDevice', 'AuPluginDevice'})

# Label used when a plugin-internal sample path carries no directory.
UNKNOWN_KIT = '(no folder)'

# Folder conventions Live and the user follow, mapped to a category.
# Order matters: the specific `Processed/*` subfolders must be tested
# before the generic `Processed` fallback, otherwise every chop would be
# classified as merely 'processed'.
SAMPLE_CATEGORY_RULES: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (('processed', 'crop'), 'crop'),
    (('processed', 'consolidate'), 'consolidate'),
    (('processed', 'reverse'), 'reverse'),
    (('processed', 'freeze'), 'freeze'),
    (('processed',), 'processed'),
    (('loops',), 'loop'),
    (('imported',), 'imported'),
    (('recorded',), 'recorded'),
)


def classify_sample_path(path: Optional[str]) -> Optional[str]:
  """Derives a sample category from the folders in its path.

  Components are compared whole, never as substrings, for the same
  reason directory skipping is: a substring test would classify a folder
  named 'Backing Loops Old' or 'Recorded Ideas' inconsistently, and
  worse, would match unrelated words.

  Args:
    path: A sample path, absolute or relative to the project.

  Returns:
    One of the category labels in `SAMPLE_CATEGORY_RULES`, or None when
    the path follows no recognised convention.
  """
  if not path:
    return None
  parts = {
      part.strip().lower()
      for part in path.replace('\\', '/').split('/')
      if part.strip()
  }
  # Drop the filename; only folders carry the convention.
  for required, label in SAMPLE_CATEGORY_RULES:
    if all(component in parts for component in required):
      return label
  return None


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


class LiveSetSampleRef:
  """A reference to a sample file inside an Ableton Live set.

  Handles the several `FileRef` layouts Live has used over the years:
  modern sets expose `Path` / `RelativePath` elements carrying a `Value`
  attribute, while older sets store the filename in `Name` and the
  directory chain as a list of `RelativePathElement` entries.
  """

  def __init__(self, elem: ET.Element, source: str = 'unknown'):
    self.source = source
    self.path: Optional[str] = None
    self.relative_path: Optional[str] = None
    self.name: Optional[str] = None

    file_ref = elem.find('FileRef')
    if file_ref is not None:
      self.path = self._attr_value(file_ref.find('Path'))
      self.relative_path = self._relative_path(file_ref.find('RelativePath'))
      self.name = self._attr_value(file_ref.find('Name'))

    # Fall back to deriving the filename from whichever path we have.
    if not self.name:
      for candidate in (self.path, self.relative_path):
        if candidate:
          self.name = os.path.basename(candidate.replace('\\', '/'))
          break

    self.extension = (os.path.splitext(self.name)[1].lower()
                      if self.name else None)

    # Live stores duration in samples alongside the rate, so length can be
    # derived without opening the audio file.
    self.default_sample_rate = self._numeric(elem.find('DefaultSampleRate'),
                                             int)
    self.default_duration = self._numeric(elem.find('DefaultDuration'), int)
    self.duration_sec: Optional[float] = None
    if self.default_duration and self.default_sample_rate:
      self.duration_sec = round(
          self.default_duration / float(self.default_sample_rate), 3)

    # Filled in only when --probe-samples is used.
    self.exists_on_disk: Optional[bool] = None
    self.bit_depth: Optional[int] = None
    self.channels: Optional[int] = None
    self.size_bytes: Optional[int] = None

  @staticmethod
  def _attr_value(element: Optional[ET.Element]) -> Optional[str]:
    """Returns the `Value` attribute of an element, if present."""
    if element is None:
      return None
    return element.get('Value') or None

  @staticmethod
  def _numeric(element: Optional[ET.Element],
               vtype: Callable[[str], Any]) -> Optional[Any]:
    """Returns a type-converted `Value` attribute, or None."""
    if element is None:
      return None
    raw = element.get('Value')
    if raw is None:
      return None
    try:
      return vtype(raw)
    except (TypeError, ValueError):
      return None

  @classmethod
  def _relative_path(cls, element: Optional[ET.Element]) -> Optional[str]:
    """Resolves a relative path from either Live's modern or legacy form."""
    if element is None:
      return None
    value = element.get('Value')
    if value:
      return value
    dirs = [
        raw_dir for raw_dir in (e.get('Dir')
                                for e in element.findall(
                                    'RelativePathElement'))
        if raw_dir
    ]
    return '/'.join(dirs) if dirs else None

  def probe(self, project_dir: str) -> None:
    """Stats the sample on disk and reads WAV header metadata.

    Args:
      project_dir: Directory of the owning .als file, used to resolve
        relative paths.
    """
    candidates = []
    if self.path:
      candidates.append(self.path.replace('\\', os.sep))
    if self.relative_path:
      candidates.append(
          os.path.join(project_dir, self.relative_path.replace('\\', os.sep)))

    for candidate in candidates:
      if candidate and os.path.isfile(candidate):
        self.exists_on_disk = True
        try:
          self.size_bytes = os.path.getsize(candidate)
        except OSError:
          pass
        self._read_wav_header(candidate)
        return
    self.exists_on_disk = False

  def _read_wav_header(self, path: str) -> None:
    """Reads channel count and bit depth from a WAV header."""
    if not path.lower().endswith('.wav'):
      return
    try:
      with wave.open(path, 'rb') as handle:
        self.channels = handle.getnchannels()
        self.bit_depth = handle.getsampwidth() * 8
        if not self.default_sample_rate:
          self.default_sample_rate = handle.getframerate()
        if self.duration_sec is None and handle.getframerate():
          self.duration_sec = round(
              handle.getnframes() / float(handle.getframerate()), 3)
    except (wave.Error, EOFError, OSError):
      pass

  @property
  def category(self) -> Optional[str]:
    """Classifies the sample from the folder convention in its path.

    Live and the user both organise samples by folder: chops land in
    `Processed/Crop`, loops in `Loops`, and so on. Recovering that
    intent as a field makes the sample table filterable without
    re-parsing paths downstream.

    Returns:
      A category label, or None when no convention matches.
    """
    return classify_sample_path(self.relative_path or self.path)

  def as_dict(self) -> Dict[str, Any]:
    """Serializes the reference for JSON output."""
    return {
        'name': self.name,
        'path': self.path,
        'relative_path': self.relative_path,
        'extension': self.extension,
        'category': self.category,
        'source': self.source,
        'sample_rate': self.default_sample_rate,
        'duration_sec': self.duration_sec,
        'exists_on_disk': self.exists_on_disk,
        'bit_depth': self.bit_depth,
        'channels': self.channels,
        'size_bytes': self.size_bytes,
    }


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
  """Data for an Audio clip, including its referenced sample."""

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    sample_ref = elem.find('SampleRef')
    self.sample = (LiveSetSampleRef(sample_ref, source='audio_clip')
                   if sample_ref is not None else None)
    self.warp_markers = elem.findall('WarpMarkers/WarpMarker')
    self.is_warped = self._bool_value_for_subtag('IsWarped')


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


class LiveSetVstPresetData:
  """Best-effort recovery of readable state from a VST plugin chunk.

  VST plugin state is an opaque, vendor-defined binary blob, so there is no
  general way to parse it. In practice many plugins serialize readable
  strings into it -- Native Instruments hosts, for example, embed pad
  names, sample paths and library names. This class extracts printable
  ASCII and UTF-16LE runs and sorts them into rough categories.

  Results are heuristic. Sample paths are reliable because they are
  validated against known audio extensions; `preset_names` is a best guess.
  """

  # Guard against pathological blobs; the largest observed are ~200 KB.
  MAX_BYTES = 8 * 1024 * 1024

  _ASCII_RUN = re.compile(rb'[\x20-\x7e]{4,}')
  _UTF16_RUN = re.compile(rb'(?:[\x20-\x7e]\x00){4,}')
  _AUDIO_PATH = re.compile(
      r'[\w /\\.\-()&\']+\.(?:wav|aiff?|mp3|flac|ogg|m4a|rex2?|rx2|ncw)$',
      re.IGNORECASE)
  # Serialization scaffolding and internal keys, not user-facing names.
  _NOISE = re.compile(
      r'^(?:NI::|serialization::|\\@|[0-9.]+$|[{(\[]|.{0,2}$)')
  _LIBRARY_HINT = re.compile(r'\b(?:Library|Factory|Expansion|Pack)\b',
                             re.IGNORECASE)

  # A human-authored name uses letters, digits and light punctuation.
  # Anything else ('=', '{', '"', ':', '!', '?', '#', backtick) marks a
  # code or serialization fragment such as 'midiMap = {'.
  _ALLOWED_NAME = re.compile(r"^[A-Za-z0-9 _\-'&.()]+$")
  # GUIDs and hex digests, e.g. 'EC4D6957-197C-E311-937A-F0DEF1BE5559'.
  _GUID_LIKE = re.compile(r'^[0-9A-Fa-f]{6,}-|^\{?[0-9A-Fa-f-]{16,}\}?$')
  # Four-character chunk identifiers, optionally trailed by a stray byte
  # picked up from the surrounding binary, e.g. 'DSINe' from 'NISD'.
  _MAGIC_SHAPE = re.compile(r'^[A-Z0-9_]{2,8}[a-z]{0,2}$')
  _WORD = re.compile(r'[a-z0-9]+')

  # Format markers that appear verbatim inside plugin chunks. Both the
  # forward and byte-reversed spellings are listed because little-endian
  # four-character codes surface backwards ('data' -> 'atad').
  _BINARY_TOKENS = frozenset({
      'data', 'atad',
      'zlibinfo', 'ofnibilz',
      'nisd', 'dsin',
      'riff', 'ffir',
      'wave', 'evaw',
      'junk', 'knuj',
      'list', 'tsil',
      'info', 'ofni',
      'ccnk', 'kncc',
      'fpch', 'hcpf',
      'fbch', 'hcbf',
      'vstw', 'wtsv',
      'chunk', 'knuhc',
      'header', 'redaeh',
      'plist', 'bplist',
      'magic', 'cigam',
      'params', 'smarap',
      'buffer', 'reffub',
      'stream', 'maerts',
      'document', 'tnemucod',
  })

  # Markers long enough to be unambiguous as a prefix. A marker often
  # carries a trailing byte from the surrounding binary, so 'zlibinfo'
  # surfaces as 'ofnibilzD'. Short tokens are excluded because they would
  # match ordinary words.
  _LONG_BINARY_PREFIXES = tuple(
      token for token in _BINARY_TOKENS if len(token) >= 6)

  def __init__(self, hex_text: str):
    self.byte_size = 0
    self.sample_paths: List[str] = []
    self.libraries: List[str] = []
    self.preset_names: List[str] = []

    data = self._decode(hex_text)
    if not data:
      return
    self.byte_size = len(data)

    runs = self._extract_runs(data)
    self._classify(runs)

  @classmethod
  def _decode(cls, hex_text: str) -> bytes:
    """Converts the hex-encoded chunk into raw bytes."""
    if not hex_text:
      return b''
    hex_chars = ''.join(c for c in hex_text if c in '0123456789abcdefABCDEF')
    # An odd count means a truncated chunk; drop the dangling nibble.
    hex_chars = hex_chars[:len(hex_chars) // 2 * 2]
    if len(hex_chars) // 2 > cls.MAX_BYTES:
      logger.debug('Skipping oversized plugin chunk (%d bytes)',
                   len(hex_chars) // 2)
      return b''
    try:
      return bytes.fromhex(hex_chars)
    except ValueError:
      return b''

  @classmethod
  def _extract_runs(cls, data: bytes) -> List[str]:
    """Pulls printable ASCII and UTF-16LE string runs out of the blob."""
    runs = []
    for match in cls._ASCII_RUN.findall(data):
      runs.append(match.decode('ascii', 'replace'))
    for match in cls._UTF16_RUN.findall(data):
      runs.append(match.decode('utf-16-le', 'replace'))
    return runs

  def _classify(self, runs: List[str]) -> None:
    """Sorts raw string runs into paths, libraries and preset names."""
    seen_paths = set()
    seen_libs = set()
    seen_names = set()

    for raw in runs:
      # Binary length prefixes often leave stray leading punctuation.
      value = raw.strip().lstrip(',+.-*/\\ \t')
      if not value:
        continue

      if self._AUDIO_PATH.match(value):
        if value not in seen_paths:
          seen_paths.add(value)
          self.sample_paths.append(value)
        continue

      if self._NOISE.match(value):
        continue

      if self._LIBRARY_HINT.search(value) and len(value) < 80:
        if value not in seen_libs:
          seen_libs.add(value)
          self.libraries.append(value)
        continue

      # Remaining runs are candidate preset/pad names.
      if self._is_plausible_name(value) and value not in seen_names:
        seen_names.add(value)
        self.preset_names.append(value)

  @classmethod
  def _is_plausible_name(cls, value: str) -> bool:
    """Heuristic filter for human-authored preset and pad names.

    String runs scraped from a binary chunk are overwhelmingly noise:
    byte-reversed chunk IDs ('atad' from 'data', 'ofnibilz' from
    'zlibinfo'), four-character magic markers with a stray trailing byte
    ('DSINe'), GUIDs, and fragments of embedded config ('midiMap = {').

    Each rejection below targets one of those observed failure classes.
    The filter errs toward dropping real names rather than admitting
    noise, because a polluted counter is worse than a short one.

    Args:
      value: A candidate string run.

    Returns:
      True if the value looks like a name a person would recognise.
    """
    if not 5 <= len(value) <= 64:
      return False
    # Paths are classified separately.
    if '/' in value or '\\' in value:
      return False
    # Code and serialization fragments, e.g. 'name = "Noise Amount",'.
    if not cls._ALLOWED_NAME.match(value):
      return False
    # GUIDs and hex digests.
    if cls._GUID_LIKE.match(value):
      return False
    # Chunk identifiers such as 'DSINe', 'DSINj', 'DSINl'.
    if cls._MAGIC_SHAPE.match(value):
      return False

    words = cls._WORD.findall(value.lower())
    # Match as a prefix too: a marker often carries a trailing byte from
    # the surrounding binary, e.g. 'ofnibilzD' from 'zlibinfo'.
    for word in words:
      if word in cls._BINARY_TOKENS:
        return False
      if word.startswith(cls._LONG_BINARY_PREFIXES):
        return False

    # Long unbroken runs are encoded patch data, not names. Real names of
    # this length contain spaces, e.g. Zebra2 emits 64-character blobs
    # like 'lcjiWTlcfmombiAohkdglbmaeA6tIA10eiSHGhcKglLgoHdeHfcKRQRL'.
    if len(value) > 24 and ' ' not in value:
      return False

    letters = [c for c in value if c.isalpha()]
    if len(letters) < 3:
      return False

    # A high hex-character ratio means a digest, not a name. Hex letters
    # include 'a' and 'e', so digests otherwise pass the vowel test.
    hex_chars = sum(1 for c in value if c in '0123456789abcdefABCDEF-')
    if len(value) >= 8 and hex_chars / len(value) > 0.85:
      return False

    # Require at least one pronounceable word, which random byte runs
    # such as 'UU7CksA' do not have.
    if not any(len(w) >= 3 and set(w) & set('aeiou') for w in words):
      return False

    vowels = sum(1 for c in letters if c.lower() in 'aeiou')
    if vowels / len(letters) < 0.2:
      return False

    return True

  @property
  def sample_names(self) -> List[str]:
    """Bare filenames of any samples referenced inside the plugin state."""
    return [
        os.path.basename(p.replace('\\', '/')) for p in self.sample_paths
    ]

  def sample_kits(self,
                  max_kits: int = 32,
                  max_names_per_kit: int = 32) -> List[Dict[str, Any]]:
    """Groups the recovered sample paths by their containing directory.

    A plugin kit typically references dozens of samples that all live under
    one folder, so storing every full path repeats the same prefix over and
    over. Grouping by directory keeps the record small while remaining
    sufficient to locate the samples on disk.

    Args:
      max_kits: Maximum number of kit directories to return.
      max_names_per_kit: Maximum filenames to list within each kit.

    Returns:
      Kit entries sorted by sample count (descending), each holding the
      directory, the total number of samples found in it, and the
      filenames.
    """
    kits: Dict[str, List[str]] = {}
    for raw_path in self.sample_paths:
      normalized = raw_path.replace('\\', '/')
      directory, _, filename = normalized.rpartition('/')
      kits.setdefault(directory or UNKNOWN_KIT, []).append(filename)

    ordered = sorted(kits.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [{
        'path': directory,
        'count': len(names),
        'samples': names[:max_names_per_kit],
    } for directory, names in ordered[:max_kits]]

  def as_dict(self,
              max_names: int = 50,
              full_paths: bool = False) -> Dict[str, Any]:
    """Serializes the recovered state.

    Samples are summarized as kit directories rather than a flat list of
    full paths; the redundant per-file paths added thousands of lines per
    run without adding information. The heuristic name lists are capped
    since they are noisier.

    Args:
      max_names: Cap on the library and preset name lists.
      full_paths: Also emit every raw sample path. Off by default; useful
        for debugging the extraction heuristics.

    Returns:
      A JSON-serializable summary of the plugin chunk.
    """
    info: Dict[str, Any] = {
        'byte_size': self.byte_size,
        'sample_count': len(self.sample_paths),
        'sample_kits': self.sample_kits(),
        'libraries': self.libraries[:max_names],
        'preset_names': self.preset_names[:max_names],
    }
    if full_paths:
      info['sample_paths'] = self.sample_paths
    return info


class LiveSetDeviceData(ALSNode):
  """Data for a device in an Ableton Live set."""

  def __init__(self, elem: ET.Element):
    super().__init__(elem)
    self.device_type = elem.tag
    buffer_element = elem.find('PluginDesc/AuPluginInfo/Preset/AuPreset/Buffer')
    self.au_preset_buffer = (LiveSetAuPluginPresetData(buffer_element.text)
                             if buffer_element is not None and
                             buffer_element.text else None)
    self.au_preset_name = (self.au_preset_buffer.name
                           if self.au_preset_buffer else None)

    name_element = elem.find('PluginDesc/AuPluginInfo/Name')
    self.preset_name = (
        self._value_for_subtag('UserName') or
        (name_element.get('Value') if name_element is not None else None) or
        self._value_for_subtag('PluginDesc/VstPluginInfo/PlugName') or '')
    self.name = f'{self.device_type}: {self.preset_name}'

    # Plugin binary location, useful for tracking down a missing plugin.
    self.plugin_path = (
        self._value_for_subtag('PluginDesc/VstPluginInfo/Path') or
        self._value_for_subtag('PluginDesc/AuPluginInfo/Path'))

    # VST state is an opaque chunk, but usually carries readable strings:
    # kit names, preset names and the sample paths a plugin loaded.
    self.vst_preset: Optional[LiveSetVstPresetData] = None
    vst_buffer = elem.find('PluginDesc/VstPluginInfo/Preset/VstPreset/Buffer')
    if vst_buffer is None:
      # Layout varies between Live versions; fall back to a scoped search.
      plugin_desc = elem.find('PluginDesc/VstPluginInfo')
      if plugin_desc is not None:
        vst_buffer = next(
            (b for b in plugin_desc.iter('Buffer') if (b.text or '').strip()),
            None)
    if vst_buffer is not None and (vst_buffer.text or '').strip():
      self.vst_preset = LiveSetVstPresetData(vst_buffer.text or '')

    # Simpler, Sampler and Drum Rack chains reference their samples from
    # nested SampleRef nodes rather than from clips, so search the whole
    # device subtree.
    self.samples = [
        LiveSetSampleRef(e, source='device')
        for e in elem.findall('.//SampleRef')
    ]

    if self.device_type in PLUGIN_DEVICE_TAGS:
      self.kind = 'plugin'
    elif self.device_type in INSTRUMENT_DEVICE_TAGS:
      self.kind = 'instrument'
    else:
      self.kind = 'effect'


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

    # Check arrangement clips too, which live under
    # MainSequencer/Track/ArrangerAutomation/Events/...
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
    tempo_elem = self.live_set.find('.//o:Tempo/o:Manual',
                                    namespaces={'o': '*'})
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
    self.creator = self.root.get('Creator')

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
        notes = [
            'C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'
        ]
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

    # Locators / arrangement markers
    self.locators: List[Dict[str, Any]] = []
    for loc_elem in self.live_set.findall('.//Locators/Locators/Locator'):
      name_elem = loc_elem.find('Name')
      time_elem = loc_elem.find('Time')
      loc_name = name_elem.get('Value') if name_elem is not None else None
      loc_time = float(time_elem.get('Value', 0)) if time_elem is not None else 0.0
      if loc_name is not None:
        self.locators.append({'name': loc_name, 'time': loc_time})

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
                   include_midi_clips: bool = False,
                   include_audio_clips: bool = True,
                   probe_samples: bool = False) -> Dict[str, Any]:
  """Extracts project information from an Ableton Live file (.als).

  Args:
    path: Path to the .als file.
    include_midi_clips: Emit per-track MIDI clip details.
    include_audio_clips: Emit per-track audio clip details.
    probe_samples: Stat referenced samples on disk and read WAV headers.
      Slower, but yields bit depth, channel count and existence.

  Returns:
    A dictionary describing the project, its tracks, devices and samples.
  """

  lsd = LiveSetData(path)
  name, ext = os.path.splitext(path)
  if ext != '.als':
    raise ValueError(f'Expected .als file, got {ext}')

  project_dir = os.path.dirname(path)

  project: Dict[str, Any] = {
      'path': path,
      'name': os.path.basename(name),
      'ableton_version_full': lsd.ableton_version,
      'ableton_creator': lsd.creator,
      'tracks': [],
      'samples': [],
      'locators': lsd.locators,
      'num_locators': len(lsd.locators),
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
    counters['ableton_version_full'].update([lsd.ableton_version])
  if lsd.creator:
    counters['ableton_creator'].update([lsd.creator])

  for loc in lsd.locators:
    counters['locators'].update([loc['name']])

  counters['creation_year'].update([str(int(lsd.creation_time.year))])
  counters['last_modified_year'].update([str(int(lsd.modified_time.year))])

  samples: List[Dict[str, Any]] = []

  def _record_sample(ref: Optional['LiveSetSampleRef'], track_index: int,
                     clip_name: Optional[str]) -> None:
    """Probes, counts and appends a single sample reference."""
    if ref is None or not ref.name:
      return
    if probe_samples:
      ref.probe(project_dir)
    entry = ref.as_dict()
    entry['track_index'] = track_index
    entry['clip_name'] = clip_name
    samples.append(entry)
    counters['sample_files'].update([ref.name])
    if ref.extension:
      counters['sample_extensions'].update([ref.extension])
    counters['sample_sources'].update([ref.source])
    category = ref.category
    if category:
      counters['sample_categories'].update([category])
    if ref.exists_on_disk is False:
      counters['samples_missing'].update([ref.name])

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
      device_entry: Dict[str, Any] = {
          'type': dev.device_type,
          'preset': dev.preset_name,
          'kind': dev.kind,
      }
      if dev.plugin_path:
        device_entry['plugin_path'] = dev.plugin_path

      counters['device_types'].update([dev.device_type])
      counters['device_kinds'].update([dev.kind])
      if dev.kind == 'effect':
        counters['effects'].update([dev.device_type])
      elif dev.kind == 'instrument':
        counters['instruments'].update([dev.device_type])
      if dev.device_type == 'PluginDevice':
        counters['plugins_vst'].update([dev.preset_name])
      elif dev.device_type == 'AuPluginDevice':
        counters['plugins_au'].update([dev.preset_name])
      if dev.au_preset_name:
        counters['au_presets'].update(
            [f'{dev.preset_name}: {dev.au_preset_name}'])

      # Readable state recovered from the opaque VST chunk.
      if dev.vst_preset and dev.vst_preset.byte_size:
        preset_info = dev.vst_preset.as_dict()
        device_entry['vst_preset'] = preset_info
        for library in dev.vst_preset.libraries:
          counters['vst_libraries'].update([library])
        for preset_label in dev.vst_preset.preset_names[:10]:
          counters['vst_strings'].update(
              [f'{dev.preset_name}: {preset_label}'])
        if dev.vst_preset.sample_paths:
          counters['plugins_with_samples'].update([dev.preset_name])

        # Surface the plugin's internal samples as kit-level rows. One row
        # per file would add thousands of near-identical lines that only
        # repeat the same folder prefix; the kit folder plus its filenames
        # is enough to track any individual sample down on disk.
        for kit in dev.vst_preset.sample_kits():
          kit_path = kit['path']
          kit_names = kit['samples']
          kit_category = classify_sample_path(kit_path)
          if kit_category:
            counters['sample_categories'].update([kit_category])
          samples.append({
              'name': os.path.basename(kit_path.rstrip('/')) or kit_path,
              'path': kit_path,
              'relative_path': None,
              'extension': None,
              'category': kit_category,
              'source': 'plugin_kit',
              'sample_rate': None,
              'duration_sec': None,
              'exists_on_disk': None,
              'bit_depth': None,
              'channels': None,
              'size_bytes': None,
              'track_index': i,
              'clip_name': dev.name,
              'plugin': dev.preset_name,
              'sample_count': kit['count'],
              'sample_names': '|'.join(kit_names),
          })
          counters['plugin_sample_kits'].update([kit_path])
          counters['sample_sources'].update(['plugin_kit'])

          # Per-file detail stays in the counters, which aggregate
          # cheaply, so filename-level search is not lost.
          for internal_name in kit_names:
            counters['plugin_sample_files'].update([internal_name])
            extension = os.path.splitext(internal_name)[1].lower()
            if extension:
              counters['sample_extensions'].update([extension])

      track_info['devices'].append(device_entry)

      # Samples living inside Simpler / Sampler / Drum Rack chains.
      for ref in dev.samples:
        _record_sample(ref, i, dev.name)

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

    if include_audio_clips:
      track_info['audio_clips'] = []

    # Named distinctly from the MIDI clip loop above: reusing `clip`
    # makes the type checker infer a single conflicting clip type.
    for audio_clip in track_data.audio_clips:
      if include_audio_clips:
        track_info['audio_clips'].append({
            'name': audio_clip.name,
            'length': audio_clip.length,
            'is_loop': audio_clip.loop_on,
            'is_warped': audio_clip.is_warped,
            'warp_markers': len(audio_clip.warp_markers),
            'sample': (audio_clip.sample.name
                       if audio_clip.sample else None),
        })
      if audio_clip.loop_on is not None:
        counters['audio_clip_is_loop'].update([str(audio_clip.loop_on)])
      if audio_clip.warp_markers:
        counters['warp_markers'].update(
            {'total': len(audio_clip.warp_markers)})
      _record_sample(audio_clip.sample, i, audio_clip.name)

    if isinstance(project['tracks'], list):
      project['tracks'].append(track_info)

  project['samples'] = samples
  project['num_samples'] = len(samples)
  project['num_unique_samples'] = len({
      s['name'] for s in samples if s.get('name')
  })
  num_audio_clips = 0
  num_midi_clips = 0
  for track in all_tracks:
    if not track:
      continue
    num_audio_clips += len(track.audio_clips)
    num_midi_clips += len(track.midi_clips)
  project['num_audio_clips'] = num_audio_clips
  project['num_midi_clips'] = num_midi_clips

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
    """Formats counters as 'name (count)' pairs, preserving multiplicity."""
    formatted = {}
    for name, counter in counters.items():
      if counter and (len(counter) > 1 or
                      (len(counter) == 1 and list(counter.values())[0] != 0)):
        formatted[name] = ', '.join(
            f'{key} ({count})' if count > 1 else str(key)
            for key, count in counter.items())
    return formatted

  # 'samples' and 'locators' are lists; keeping them here would put an
  # unreadable nested list into every row.
  skip_keys = ['counters', 'tracks', 'samples', 'locators']
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


def should_skip_dir(dirpath: str, skip_folders: Tuple[str, ...]) -> bool:
  """Reports whether a directory should be excluded from the walk.

  Matches whole path components. A naive substring test would also match
  unrelated names -- 'old' is a substring of 'folder', 'Gold' and 'Bold' --
  which silently removes real projects from the index.

  Args:
    dirpath: Directory being considered.
    skip_folders: Folder names to exclude.

  Returns:
    True if any path component exactly matches a skip entry.
  """
  normalized = os.path.normpath(dirpath)
  components = set(normalized.split(os.sep))
  if os.altsep:
    components.update(normalized.split(os.altsep))
  return bool(components & set(skip_folders))


def load_projects_in_dir(project_dir: str,
                         skip_folders: Tuple[str, ...] = tuple(SKIP_FOLDERS),
                         save_info_json: bool = False,
                         include_midi_clips: bool = False,
                         probe_samples: bool = False) -> Dict[str, Any]:
  """Load information for all .als projects in a directory.

  Args:
    project_dir: Root directory to walk.
    skip_folders: Folder names excluded by whole-component match.
    save_info_json: Write a sidecar .json of counters next to each project.
    include_midi_clips: Emit per-track MIDI clip details.
    probe_samples: Stat samples on disk and read WAV headers.

  Returns:
    Mapping of project name to parsed project information.
  """
  project_ext = '.als'
  project_info = {}
  t0 = time.time()
  error_count = 0
  errors: List[Tuple[str, str]] = []
  logger.info(f'Loading projects in {project_dir}...')

  for dirpath, _, filenames in os.walk(project_dir):
    if should_skip_dir(dirpath, skip_folders):
      continue
    for filename in filenames:
      key, ext = os.path.splitext(filename)
      if ext == project_ext and not key.startswith('.'):
        full_filename = os.path.join(dirpath, filename)
        logger.info(f'Reading: {key}')
        try:
          info = parse_als_info(full_filename,
                                include_midi_clips=include_midi_clips,
                                probe_samples=probe_samples)
          if save_info_json:
            # Write the complete record, not just counters, so each
            # project's JSON is self-contained.
            json_info_file = full_filename.replace(project_ext, '.json')
            save_dict_as_json(json_info_file, info, sort=False)
          project_info[key] = info
        except Exception as e:  # pylint: disable=broad-except
          # Keep going, but never fail silently -- an uncounted parse error
          # is indistinguishable from a project that does not exist.
          error_count += 1
          errors.append((full_filename, str(e)))
          logger.error(f'Failed to parse {full_filename}: {e}')

  elapsed = time.time() - t0
  logger.info(f'Loaded {len(project_info)} projects with '
              f'{error_count} errors in {elapsed:.2f} seconds.')
  if errors:
    logger.warning('Projects that failed to parse:')
    for failed_path, message in errors:
      logger.warning(f'  {failed_path}: {message}')

  return project_info


def create_samples_df(project_info: Dict[str, Any],
                      tsv_path: Optional[str] = None) -> pd.DataFrame:
  """Builds a flat sample-level table across all projects.

  One row per sample reference, which is what makes sample-oriented
  filtering (by filename, extension, duration, project) practical.

  Args:
    project_info: Parsed project information.
    tsv_path: Optional path to write the table as TSV.

  Returns:
    A DataFrame with one row per sample reference.
  """
  rows = []
  for project in project_info.values():
    if 'error' in project:
      continue
    for sample in project.get('samples', []):
      row = dict(sample)
      row['project'] = project.get('name')
      row['project_path'] = project.get('path')
      rows.append(row)

  df = pd.DataFrame(rows)
  logger.info(f'Created samples DataFrame with shape {df.shape}')
  if tsv_path:
    os.makedirs(os.path.dirname(tsv_path), exist_ok=True)
    df.to_csv(tsv_path, sep='\t', index=False)
  return df


def run_parser(
    project_dir: str = PROJECT_DIR,
    skip_dirs: Tuple[str, ...] = tuple(SKIP_FOLDERS),
    output_dir: str = OUTPUT_DIR,
    save_project_json: bool = False,
    include_midi_clips: bool = False,
    probe_samples: bool = False
) -> Tuple[Dict[str, Any], Dict[str, Any], pd.DataFrame]:
  """Main entry point for parsing Ableton Live projects."""
  logger.info(f'Starting parser in {project_dir}')
  logger.info(f'Skipping folders: {skip_dirs}')

  os.makedirs(output_dir, exist_ok=True)

  project_info = load_projects_in_dir(project_dir,
                                      skip_folders=skip_dirs,
                                      save_info_json=save_project_json,
                                      include_midi_clips=include_midi_clips,
                                      probe_samples=probe_samples)

  save_info(output_dir, project_info, prefix=CACHE_INFO_FILE)

  project_df = create_project_df(project_info, tsv_path=PROJECT_TSV)
  create_samples_df(project_info, tsv_path=SAMPLES_TSV)
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
  parser.add_argument('--include-midi-clips',
                      action='store_true',
                      help='Include per-track MIDI clip details')
  parser.add_argument('--probe-samples',
                      action='store_true',
                      help='Stat samples on disk and read WAV headers for '
                      'bit depth, channels and missing-file detection')
  args = parser.parse_args()

  setup_logging(args.debug)

  try:
    run_parser(project_dir=args.root,
               save_project_json=args.save_json,
               include_midi_clips=args.include_midi_clips,
               probe_samples=args.probe_samples)
  except Exception:
    logger.exception("Fatal error in main execution")
    sys.exit(1)
