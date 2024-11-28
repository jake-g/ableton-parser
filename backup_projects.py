#@title Imports

from pprint import pprint
import os
import sys
import pickle
import time
from datetime import datetime

#@title Library

import xml.etree.ElementTree as ET
import gzip
import plistlib

def bind(val, f):
    return (val is not None) and f(val) or None

hexchars = set('0123456789abcdef')
def decodeHexString(str):
    """Decode a hex string, ignoring all non-hex characters"""
    return filter(lambda c:c in hexchars, str.lower()).decode('hex')

def hideUnprintable(str, maskchar='.'):
    return ''.join(map(lambda c:(ord(c)>0x1f and ord(c)<0x7e) and c or maskchar, str))

def decodeTimeSignature(encoded):
    """Convert an Ableton Live integer-encoded time signature into a 
       (numerator,denominator) tuple"""
    return (encoded%99+1, 1<<(encoded/99))

#  ---- classes

# the boolean value type:
def BoolValue(str): return  (str == "true")

# return the type function for a string value
def guessTypeForValue(v):
    if (v in ('true','false')): return BoolValue
    for fn in (int, float):
        try:
            if fn(v) is not None: 
                return fn
        except ValueError:
            pass
    return None  # just a string

class ALSNode(object):
    """
    The parent class of all .als nodes
    """

    # the value fields we automatically extract from the element; each one 
    # has a name mapped to a type/conversion function; i.e., "Time" : float .

    valuefields = {}

    def __init__(self, elem):
        self.elem = elem
        # populate instance vars using harvested Value attributes from the element or subelements
        for (key, fspec) in self.valuefields.iteritems():
            if type(fspec) == dict:
                (sel, ivar, vtype ) = (fspec.get('sel',key),fspec.get('ivar',key),fspec.get('type',None))
            elif type(fspec) == tuple:  # A simple (type, sel) tuple
                (sel, ivar, vtype) = (fspec[1], key, fspec[0])
            else:
                (sel, ivar, vtype) = (key, key[0].lower()+key[1:], fspec)
            val = self.valueForSubtag(sel)
            if val:
                if vtype:
                    try:
                        val = vtype(val)
                    except ValueError:
                        pass
            self.__dict__[ivar] = val


    def valueForSubtag(self, selector):
        return bind(self.elem.find(selector), lambda e: e.get("Value"))

    def valueForSubtagWithType(self, selector, type):
        if type is None: type = lambda x:x
        try:
            return type(self.valueForSubtag(selector))
        except ValueError:
            return None

    def intValueForSubtag(self, selector):
        return self.valueForSubtagWithType(selector, int)

    def floatValueForSubtag(self, selector):
        return self.valueForSubtagWithType(selector, float)

    def boolValueForSubtag(self, selector):
        return self.valueForSubtag(selector) == 'true'


# A node representing an automatable parameter

class ALSTrackMixerParam(ALSNode):
    def __init__(self, elem):
        super(ALSTrackMixerParam, self).__init__(elem)
        # determine the element type
        manual = self.valueForSubtag("Manual")
        self.type = guessTypeForValue(manual) 
        typefunc = self.type and self.type or (lambda x:x)
        self.manual = typefunc(manual)
        self.events = [ (int(e.get('Time')), typefunc(e.get('Value'))) for e in elem.findall("ArrangerAutomation/Events/*")]


class ALSTrackMixer(ALSNode):
    def __init__(self, elem):
        super(ALSTrackMixer, self).__init__(elem)
        self.params = dict([(e.tag, ALSTrackMixerParam(e)) for e in elem.findall("*[ArrangerAutomation]")])

# Clips and their component classes

class ALSWarpMarker(object):
    def __init__(self, elem):
        self.secTime = float(elem.get('SecTime'))
        self.beatTime = float(elem.get('BeatTime'))

class ALSMidiNote(object):
    def __init__(self, key, elem):
        # for some reason, Live stores MIDI velocities as floating-point values
        self.time, self.key, self.duration, self.velocity, self.offVelocity, self.isEnabled = (float(elem.get("Time")), key, float(elem.get("Duration")), float(elem.get("Velocity")), int(elem.get("OffVelocity")), 
            elem.get("IsEnabled")=="true")

class LiveSetMidiClipData(ALSNode):
    """
    An object encapsulating a MidiClip node.
    """
    valuefields = { 
      'Name': None, 'Annotation': None, 'LaunchMode':int, 'CurrentStart':float, 'CurrentEnd':float,  
      'loopStart' : (float, "Loop/LoopStart"), 'loopEnd' : (float, "Loop/LoopEnd"), 
      'loopStartRelative' : (float, "Loop/LoopStartRelative"), 
    }
    def __init__(self, elem):
        super(LiveSetMidiClipData, self).__init__(elem)
        self.warpmarkers = [ ALSWarpMarker(e) for e in elem.findall("WarpMarkers/WarpMarker")]
        self.length = (self.currentStart is not None and self.currentEnd is not None) and self.currentEnd-self.currentStart or None
        self.loopOn = self.boolValueForSubtag("Loop/LoopOn")
        self.loopLength = (self.loopStart is not None and self.loopEnd is not None) and self.loopEnd-self.loopStart or None

        self.notes = []
        for ktrk in elem.findall("Notes/KeyTracks/KeyTrack"):
            note = bind(ktrk.find("MidiKey"), lambda e:int(e.get("Value")))
            self.notes.extend([ALSMidiNote(note, mne) for mne in ktrk.findall("Notes/MidiNoteEvent")])
        self.notes.sort(key=lambda mn:mn.time)


# Devices 

class LiveSetAuPluginPresetData(object):
    """
    An object encapsulating the data stored in a preset buffer
    """
    def __init__(self, text):
        self.text = decodeHexString(text)
        self.plist = plistlib.readPlistFromString(self.text)
        self.name = self.plist.get('name')

class LiveSetDeviceData(ALSNode):
    """
    An object encapsulating the data for a device
    """
    def __init__(self, elem):
        super(LiveSetDeviceData, self).__init__(elem)
        self.deviceType = elem.tag
        self.auPresetBuffer = bind(elem.find("PluginDesc/AuPluginInfo/Preset/AuPreset/Buffer"), lambda e:LiveSetAuPluginPresetData(e.text))
        self.auPresetName = bind(self.auPresetBuffer, lambda b:b.name)

        self.presetName = self.valueForSubtag("UserName") \
                or bind(elem.find("PluginDesc/AuPluginInfo/Name"), lambda e:e.get("Value")) \
                or self.valueForSubtag("PluginDesc/VstPluginInfo/PlugName") \
                or ""
        self.name = "%s: %s"%(self.deviceType, self.presetName)

# Tracks

class LiveSetTrackData(ALSNode):
    """
    An object encapsulating the data for a Track
    """
    valuefields = { 'Name' : None }
    def __init__(self, elem):
        super(LiveSetTrackData, self).__init__(elem)
        self.trackType = elem.tag
        self.devices = [LiveSetDeviceData(c) for c in elem.find("DeviceChain/DeviceChain/Devices")]

        self.mixer = bind(elem.find("DeviceChain/Mixer"), ALSTrackMixer)

        # TODO: encapsulate these in a class
        self.clipslots = bind(elem.find("DeviceChain/MainSequencer/ClipSlotList"), lambda x:x.findall("ClipSlot")) or []
        self.midiclips = bind(elem.find("DeviceChain/MainSequencer/ClipSlotList"), lambda x:[LiveSetMidiClipData(c) for c in x.findall(".//MidiClip")]) or []


class LiveSetData(object):
    """
    An object encapsulating a parsed Live set.
    """
    def __init__(self, path):
        self.etree = ET.parse(gzip.GzipFile(path))
        self.live_set = self.etree.getroot().find("LiveSet")
        self.tracks = [LiveSetTrackData(c) for c in self.live_set.find("Tracks")]
        self.mastertrack = bind(self.live_set.find("MasterTrack"), LiveSetTrackData)

    def timeSignatures(self):
        """Return an array of (beat time, (num,denom)) time signatures used in the track."""
        return [(max(t,0), decodeTimeSignature(enc)) for (t,enc) in self.mastertrack.mixer.params['TimeSignature'].events]

#@title Parse .als

def parse_als_info(path):
    """Print out some info about an Ableton Live set at a path"""
    lsd = LiveSetData(path)
    name, ext = os.path.splitext(path)
    assert ext == '.als'
    # pprint(lsd.__dict__)
    info = {
        'path': path, 
        'name': os.path.basename(name),
        'project': os.path.dirname(name).split('/')[-1].replace(' Project', ''),
        'tracks': []
    }
    all_tracks = lsd.tracks + [lsd.mastertrack]
    for i, t in enumerate(all_tracks):
      i = i+1 # start at 1
      if not t:
          print('  SKIPPING %s track %d' % (t, i))
          continue
      # pprint(t.__dict__)
      # Note: clipSLots field not used (not sure what its good for). 
      #   Also not using .elem (which is a raw field)
      
      track = {'index': i, 'type': t.trackType, 'devices': [], 'clips': []}
      for dev in t.devices:
        track['devices'].append({
            'type': dev.deviceType, 
            'preset': dev.presetName
        })

      for clip in t.midiclips:
        track['clips'].append({
            'name': clip.name,
            'length': clip.length, 
            'is_loop': clip.loopOn
        })
      
      info['tracks'].append(track)
      
      # FIXME: seems these fields are unset or broken
      if t.mixer.params != {}:
        print(' DEBUG: track has mixer params most likely older project')
      if t.name != None:
        print(' DEBUG: track has name(which is rare): %s' % t.name)

    return info

#@title Save and Load Info
def save_info(cache_dir, info_dict, prefix):
    save_path = os.path.join(cache_dir, '%s.%d' % (prefix, time.time()))
    timestamp = int(save_path.split('.')[-1])
    save_date = datetime.fromtimestamp(timestamp)
    print('Saving %s from %s.' % (prefix, save_date))
    with open(save_path, 'wb') as handle:
        pickle.dump(info_dict, handle, protocol=pickle.HIGHEST_PROTOCOL)
    sys.stdout.flush()
    return save_path

def load_info(cache_dir, prefix='project_info', cache_file='', load_most_recent=True):
  cache = sorted([f for f in os.listdir(cache_dir) if prefix in f])
  if cache_file not in cache or load_most_recent:
    cache_file = cache[-1]
  cache_path = os.path.join(cache_dir, cache_file)
  timestamp = int(cache_path.split('.')[-1])
  cache_date = datetime.fromtimestamp(timestamp)
  t0 = time.time()
  print('Loading %s from %s.' % (prefix, cache_date))
  with open(cache_path, 'rb') as handle:
    info_dict = pickle.load(handle)
  print('Loaded %d projects in %d seconds.'  % (
      len(info_dict), time.time()-t0))
  return info_dict


def load_projects_in_dir(project_dir, skip_folders):
  project_info = {}
  project_errors = {}
  t0 = time.time()
  print('Loading projects in %s.' % project_dir)
  for (dirpath, dirnames, filenames) in os.walk(project_dir):
    if any(f in dirpath for f in skip_folders):
      # print 'skipping ' + dirpath
      continue
    for filename in filenames:
      key, ext = os.path.splitext(filename)
      if ext == '.als' and not key.startswith('.'): 
        full_filename = os.sep.join([dirpath, filename])
        print(' READING: %s' % key)
        try:
          project_info[key] = parse_als_info(full_filename)
        except Exception as e:
          project_errors[key] = e
          print('  ERROR: %s' % e)
        sys.stdout.flush()
  print('Loaded %d projects with %d error projects in %d seconds.' % (
      len(project_info), len(project_errors), time.time()-t0))
  return project_info, project_errors




def run_tests(project_dir = './'):
	print('TEST: parse_als_info()')
	parse_als_info(project_dir + '__Dimensions_/1 whirl tron Project/1 headphones.als')
	parse_als_info(project_dir + '_guitar beats/raw Project/raw.als')

	print('TEST: load_projects_in_dir()')
	skip_folders = ['source projects', 'Backup', 'old', 'Samples', 'Ableton Project Info'] #@param {type:"raw"}
	project_info, project_errors = load_projects_in_dir(project_dir, skip_folders)

	print('TEST: save_info()')
	saved_f = save_info(cache_dir, project_info, prefix ='project_info')
	print('TEST: load_info(cache_file="project_info.1572831091")')
	res = load_info(cache_dir, cache_file='project_info.1572831091', load_most_recent=False)
	print('TEST: load_info(load_most_recent=True')
	res = load_info(cache_dir, load_most_recent=True)


def main(args):
	project_dir = os.getcwd()
	skip_folders = [ 'Backup', 'old', 'Samples', 'Ableton Project Info', '.stfolder', '.stversions', '.ipynb_checkpoints']
	print('Project path: %s\nFound Dirs: %s\nSkipping Dirs containing: %s' % (
		project_dir, os.listdir(project_dir), skip_folders))

	cache_dir = os.path.join(project_dir, "logs/") 
	cache_prefix = "project_info"
	project_info, project_errors = load_projects_in_dir(project_dir, skip_folders)
	print('Caching project info to %s' % cache_dir)
	if project_info != {}:
		save_info(cache_dir, project_info, prefix=cache_prefix)
	if project_errors != {}: 
		save_info(cache_dir, project_info, prefix=cache_prefix+'_errors')

if __name__ == "__main__": 

	main(None)