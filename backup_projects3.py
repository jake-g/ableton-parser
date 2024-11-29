from pprint import pprint
import os
import sys
import pickle
import time
from datetime import datetime
from typing import Callable, Dict, List, Tuple, Union

import xml.etree.ElementTree as ET
import gzip
import plistlib


hexchars = set('0123456789abcdef')

# Configure project directory and folders to skip
PROJECT_DIR = os.getcwd()
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

# Configure cache directory and prefix
CACHE_DIR = os.path.join(PROJECT_DIR, "logs/")
CACHE_PREFIX = "project_info"


def _get_value_or_none(element, attribute):
    """Helper function to get an attribute value or None if it doesn't exist."""
    return element.get(attribute) if element is not None else None


def guess_type_for_value(value: str) -> Union[None, Callable]:
    if value in ('true', 'false'):
        return lambda x: x == "true"
    for function in (int, float):
        try:
            if function(value) is not None:
                return function
        except ValueError:
            pass
    return None


class ALSNode(object):
    """The parent class of all .als nodes."""

    # the value fields we automatically extract from the element; each one
    # has a name mapped to a type/conversion function; i.e., "Time" : float .
    valuefields: Dict[str, Union[Callable, Tuple, None]] = {}

    def __init__(self, element: ET.Element):
        self.element = element
        # populate instance vars using harvested Value attributes from the element or subelements
        for key, field_spec in self.valuefields.items():
            if type(field_spec) == dict:
                (selector, instance_var, value_type) = (
                    field_spec.get('sel', key),
                    field_spec.get('ivar', key),
                    field_spec.get('type', None),
                )
            elif type(field_spec) == tuple:  # A simple (type, sel) tuple
                (selector, instance_var, value_type) = (field_spec[1], key, field_spec[0])
            else:
                (selector, instance_var, value_type) = (
                    key,
                    key[0].lower() + key[1:],
                    field_spec,
                )
            value = self._get_value_or_none(selector)
            if value:
                if value_type:
                    try:
                        value = value_type(value)
                    except ValueError:
                        pass
            self.__dict__[instance_var] = value

    def _get_value_or_none(self, selector: str) -> Union[None, str]:
        element = self.element.find(selector)
        return _get_value_or_none(element, "Value")


class ALSTrackMixerParam(ALSNode):
    def __init__(self, element: ET.Element):
        super(ALSTrackMixerParam, self).__init__(element)
        manual = self._get_value_or_none("Manual")
        self.type = guess_type_for_value(manual)
        type_function = self.type or (lambda x: x)
        self.manual = type_function(manual)
        self.events = [
            (int(element.get('Time')), type_function(element.get('Value')))
            for element in element.findall("ArrangerAutomation/Events/*")
        ]


class ALSTrackMixer(ALSNode):
    def __init__(self, element: ET.Element):
        super(ALSTrackMixer, self).__init__(element)
        self.params = {
            element.tag: ALSTrackMixerParam(element)
            for element in element.findall("*[ArrangerAutomation]")
        }


class ALSWarpMarker(object):
    def __init__(self, element: ET.Element):
        self.secTime = float(element.get('SecTime'))
        self.beatTime = float(element.get('BeatTime'))


class ALSMidiNote(object):
    def __init__(self, key: int, element: ET.Element):
        # for some reason, Live stores MIDI velocities as floating-point values
        (
            self.time,
            self.key,
            self.duration,
            self.velocity,
            self.offVelocity,
            self.isEnabled,
        ) = (
            float(element.get("Time")),
            key,
            float(element.get("Duration")),
            float(element.get("Velocity")),
            int(element.get("OffVelocity")),
            element.get("IsEnabled") == "true",
        )


class LiveSetMidiClipData(ALSNode):
    """An object encapsulating a MidiClip node."""

    valuefields = {
        'Name': None,
        'Annotation': None,
        'LaunchMode': int,
        'CurrentStart': float,
        'CurrentEnd': float,
        'loopStart': (float, "Loop/LoopStart"),
        'loopEnd': (float, "Loop/LoopEnd"),
        'loopStartRelative': (float, "Loop/LoopStartRelative"),
    }

    def __init__(self, element: ET.Element):
        super(LiveSetMidiClipData, self).__init__(element)
        self.warpmarkers = [
            ALSWarpMarker(element) for element in element.findall("WarpMarkers/WarpMarker")
        ]
        self.length = (
            (self.currentStart is not None and self.currentEnd is not None)
            and self.currentEnd - self.currentStart
            or None
        )
        self.loopOn = self._get_value_or_none("Loop/LoopOn") == 'true'
        self.loopLength = (
            (self.loopStart is not None and self.loopEnd is not None)
            and self.loopEnd - self.loopStart
            or None
        )

        self.notes = []
        for key_track in element.findall("Notes/KeyTracks/KeyTrack"):
            midi_key = key_track.find("MidiKey")
            note_value = int(_get_value_or_none(midi_key, "Value"))
            self.notes.extend(
                [
                    ALSMidiNote(note_value, midi_note_event)
                    for midi_note_event in key_track.findall("Notes/MidiNoteEvent")
                ]
            )
        self.notes.sort(key=lambda midi_note: midi_note.time)


class LiveSetAuPluginPresetData(object):
    """An object encapsulating the data stored in a preset buffer."""

    def __init__(self, text: str):
        self.text = text
        try:
            # Handle potential encoding issues
            self.plist = plistlib.loads(self.text.encode('utf-8'))
        except:
            self.plist = None
        self.name = self.plist.get('name') if self.plist else None


class LiveSetDeviceData(ALSNode):
    """An object encapsulating the data for a device."""

    def __init__(self, element: ET.Element):
        super(LiveSetDeviceData, self).__init__(element)
        self.deviceType = element.tag
        self.auPresetBuffer = element.find("PluginDesc/AuPluginInfo/Preset/AuPreset/Buffer")
        if self.auPresetBuffer is not None:
            self.auPresetBuffer = LiveSetAuPluginPresetData(self.auPresetBuffer.text)
        self.auPresetName = self.auPresetBuffer.name if self.auPresetBuffer is not None else None

        self.presetName = (
            self._get_value_or_none("UserName")
            or _get_value_or_none(element.find("PluginDesc/AuPluginInfo/Name"), "Value")
            or self._get_value_or_none("PluginDesc/VstPluginInfo/PlugName")
            or ""
        )
        self.name = "%s: %s" % (self.deviceType, self.presetName)


class LiveSetTrackData(ALSNode):
    """An object encapsulating the data for a Track."""

    valuefields = {'Name': None}

    def __init__(self, element: ET.Element):
        super(LiveSetTrackData, self).__init__(element)
        self.trackType = element.tag
        self.devices = [
            LiveSetDeviceData(device)
            for device in element.find("DeviceChain/DeviceChain/Devices")
        ]

        self.mixer = element.find("DeviceChain/Mixer")
        if self.mixer is not None:
            self.mixer = ALSTrackMixer(self.mixer)

        # TODO: encapsulate these in a class
        clip_slot_list = element.find("DeviceChain/MainSequencer/ClipSlotList")
        self.clipslots = clip_slot_list.findall("ClipSlot") if clip_slot_list is not None else []
        self.midiclips = [
            LiveSetMidiClipData(clip)
            for clip in clip_slot_list.findall(".//MidiClip")
        ] if clip_slot_list is not None else []


class LiveSetData(object):
    """An object encapsulating a parsed Live set."""

    def __init__(self, path: str):
        self.etree = ET.parse(gzip.GzipFile(path))
        self.live_set = self.etree.getroot().find("LiveSet")
        self.tracks = [
            LiveSetTrackData(track) for track in self.live_set.find("Tracks")
        ]
        self.mastertrack = self.live_set.find("MasterTrack")
        if self.mastertrack is not None:
            self.mastertrack = LiveSetTrackData(self.mastertrack)

    def time_signatures(self) -> List[Tuple[int, Tuple[int, int]]]:
        """Returns an array of time signatures."""
        # Decode time signature directly in the list comprehension
        return [
            (max(time, 0), (encoded % 99 + 1, 1 << (encoded / 99)))
            for (time, encoded) in self.mastertrack.mixer.params['TimeSignature'].events
        ]


def parse_als_info(path: str) -> Dict:
    """Prints out some info about an Ableton Live set at a path."""
    live_set_data = LiveSetData(path)
    name, ext = os.path.splitext(path)
    assert ext == '.als'
    info = {
        'path': path,
        'name': os.path.basename(name),
        'project': os.path.dirname(name).split('/')[-1].replace(' Project', ''),
        'tracks': [],
    }
    all_tracks = live_set_data.tracks + [live_set_data.mastertrack]
    for index, track_data in enumerate(all_tracks):
        index = index + 1  # start at 1
        if not track_data:
            print('  SKIPPING %s track %d' % (track_data, index))
            continue

        track = {
            'index': index,
            'type': track_data.trackType,
            'devices': [],
            'clips': [],
        }
        for device in track_data.devices:
            track['devices'].append(
                {'type': device.deviceType, 'preset': device.presetName}
            )

        for clip in track_data.midiclips:
            track['clips'].append(
                {'name': clip.name, 'length': clip.length, 'is_loop': clip.loopOn}
            )

        info['tracks'].append(track)

        # FIXME: seems these fields are unset or broken
        if track_data.mixer.params != {}:
            print(' DEBUG: track has mixer params most likely older project')
        if track_data.name != None:
            print(' DEBUG: track has name(which is rare): %s' % track_data.name)

    return info


def save_info(cache_dir: str, info_dict: Dict, prefix: str) -> str:
    """Saves the project info to a cache file."""
    save_path = os.path.join(cache_dir, '%s.%d' % (prefix, time.time()))
    timestamp = int(save_path.split('.')[-1])
    save_date = datetime.fromtimestamp(timestamp)
    print('Saving %s from %s.' % (prefix, save_date))
    with open(save_path, 'wb') as handle:
        pickle.dump(info_dict, handle, protocol=pickle.HIGHEST_PROTOCOL)
    sys.stdout.flush()
    return save_path


def load_info(
    cache_dir: str,
    prefix: str = 'project_info',
    cache_file: str = '',
    load_most_recent: bool = True,
) -> Dict:
    """Loads the project info from a cache file."""
    cache = sorted([file for file in os.listdir(cache_dir) if prefix in file])
    if cache_file not in cache or load_most_recent:
        cache_file = cache[-1]
    cache_path = os.path.join(cache_dir, cache_file)
    timestamp = int(cache_path.split('.')[-1])
    cache_date = datetime.fromtimestamp(timestamp)
    start_time = time.time()
    print('Loading %s from %s.' % (prefix, cache_date))
    with open(cache_path, 'rb') as handle:
        info_dict = pickle.load(handle)
    print(
        'Loaded %d projects in %d seconds.'
        % (len(info_dict), time.time() - start_time)
    )
    return info_dict


def load_projects_in_dir(
    project_dir: str, skip_folders: List[str]
) -> Tuple[Dict, Dict]:
    """Loads all the projects in a directory."""
    project_info = {}
    project_errors = {}
    start_time = time.time()
    print('Loading projects in %s.' % project_dir)
    for dirpath, dirnames, filenames in os.walk(project_dir):
        if any(folder in dirpath for folder in skip_folders):
            continue
        for filename in filenames:
            key, ext = os.path.splitext(filename)
            if ext == '.als' and not key.startswith('.'):
                full_filename = os.sep.join([dirpath, filename])
                print(' READING: %s' % key)
                try:
                    project_info[key] = parse_als_info(full_filename)
                except Exception as error:
                    project_errors[key] = error
                    print('  ERROR: %s' % error)
                sys.stdout.flush()
    print(
        'Loaded %d projects with %d error projects in %d seconds.'
        % (len(project_info), len(project_errors), time.time() - start_time)
    )
    return project_info, project_errors


def run_tests(project_dir='./'):
    """Runs tests on the project loading and saving functions."""
    print('TEST: parse_als_info()')
    parse_als_info(
        project_dir + '__Dimensions_/1 whirl tron Project/1 headphones.als'
    )
    parse_als_info(project_dir + '_guitar beats/raw Project/raw.als')

    print('TEST: load_projects_in_dir()')
    project_info, project_errors = load_projects_in_dir(
        project_dir, SKIP_FOLDERS
    )

    print('TEST: save_info()')
    saved_file = save_info(CACHE_DIR, project_info, prefix='project_info')
    print('TEST: load_info(cache_file="project_info.1572831091")')
    result = load_info(
        CACHE_DIR, cache_file='project_info.1572831091', load_most_recent=False
    )
    print('TEST: load_info(load_most_recent=True')
    result = load_info(CACHE_DIR, load_most_recent=True)


def main(args):
    """The main function."""
    print(
        'Project path: %s\nFound Dirs: %s\nSkipping Dirs containing: %s'
        % (PROJECT_DIR, os.listdir(PROJECT_DIR), SKIP_FOLDERS)
    )

    project_info, project_errors = load_projects_in_dir(
        PROJECT_DIR, SKIP_FOLDERS
    )
    print('Caching project info to %s' % CACHE_DIR)
    if project_info != {}:
        save_info(CACHE_DIR, project_info, prefix=CACHE_PREFIX)
    if project_errors != {}:
        save_info(CACHE_DIR, project_errors, prefix=CACHE_PREFIX + '_errors')


if __name__ == "__main__":
    main(None)