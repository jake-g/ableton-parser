
import datetime
import gzip
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from parse_projects import classify_sample_path
from parse_projects import LiveSetVstPresetData
from parse_projects import load_projects_in_dir
from parse_projects import parse_als_info
from parse_projects import should_skip_dir
from parse_projects import UNKNOWN_KIT


class TestParseProjects(unittest.TestCase):

  def setUp(self):
    self.test_dir = tempfile.mkdtemp()
    self.als_path = os.path.join(self.test_dir, 'test_project.als')

  def tearDown(self):
    shutil.rmtree(self.test_dir)

  def create_mock_als(self, content, path=None):
    with gzip.open(path or self.als_path, 'wb') as f:
      f.write(content.encode('utf-8'))

  @patch('os.path.getctime')
  @patch('os.path.getmtime')
  def test_basic_parsing(self, mock_mtime, mock_ctime):
    # Mock timestamps
    mock_ctime.return_value = 1672574400  # 2023-01-01 12:00:00
    mock_mtime.return_value = 1672574400
    xml_content = """
        <Ableton MajorVersion="5" MinorVersion="11.0.12">
            <LiveSet>
                <Tracks>
                    <MidiTrack>
                        <DeviceChain>
                                <Devices>
                                    <PluginDevice>
                                        <PluginDesc>
                                            <VstPluginInfo>
                                                <PlugName Value="Sylenth1" />
                                            </VstPluginInfo>
                                        </PluginDesc>
                                    </PluginDevice>
                                </Devices>
                                <MainSequencer>
                                    <ClipSlotList>
                                        <ClipSlot>
                                            <ClipSlot>
                                                <Value>
                                                    <MidiClip CurrentStart="0" CurrentEnd="4" Time="0">
                                                        <Name Value="Test Clip" />
                                                        <Loop>
                                                            <LoopOn Value="true" />
                                                        </Loop>
                                                    </MidiClip>
                                                </Value>
                                            </ClipSlot>
                                        </ClipSlot>
                                    </ClipSlotList>
                                </MainSequencer>
                        </DeviceChain>
                    </MidiTrack>
                </Tracks>
                <MasterTrack>
                    <DeviceChain>
                        <Mixer>
                            <Tempo>
                                <ArrangerAutomation>
                                    <Events>
                                        <FloatEvent Time="0" Value="120" />
                                    </Events>
                                </ArrangerAutomation>
                            </Tempo>
                            <Tempo>
                                <Manual Value="120" />
                            </Tempo>
                            <TimeSignature>
                                <Manual Value="65540" />
                            </TimeSignature>
                        </Mixer>
                    </DeviceChain>
                </MasterTrack>
                <ScaleInformation>
                    <RootNote Value="0" /> <!-- C -->
                    <Name Value="Major" />
                </ScaleInformation>
                <Locators>
                    <Locators>
                        <Locator>
                            <Name Value="Drop" />
                            <Time Value="32" />
                        </Locator>
                    </Locators>
                </Locators>
            </LiveSet>
        </Ableton>
        """
    self.create_mock_als(xml_content.strip())

    info = parse_als_info(self.als_path, include_midi_clips=True)
    self.assertEqual(info['ableton_version_full'], '11.0.12')
    self.assertEqual(info['tempo'], 120.0)
    self.assertEqual(info['scale_root'], 'C')
    self.assertEqual(info['scale_name'], 'Major')
    self.assertEqual(info['num_locators'], 1)
    self.assertEqual(info['locators'][0]['name'], 'Drop')
    self.assertEqual(info['locators'][0]['time'], 32.0)
    # Duration: Clip 0-4 beats @ 120bpm = 4 beats / 2 beats/sec = 2 seconds
    self.assertEqual(info['duration_sec'], 2.0)

    self.assertEqual(info['time_signature'], '65540')  # 4/4 decoded or raw
    expected_time = datetime.datetime.fromtimestamp(
        1672574400).strftime('%Y-%m-%d %H:%M:%S')
    self.assertEqual(info['created'], expected_time)
    self.assertEqual(len(info['tracks']), 2)  # MidiTrack + MasterTrack

    # Check plugin extraction
    midi_track = info['tracks'][0]
    self.assertEqual(len(midi_track['devices']), 1)
    self.assertEqual(midi_track['devices'][0]['preset'], 'Sylenth1')

    # Check clip extraction
    self.assertEqual(len(midi_track['midi_clips']), 1)
    self.assertEqual(midi_track['midi_clips'][0]['name'], 'Test Clip')


class TestSampleExtraction(unittest.TestCase):
  """Covers sample references, which were previously not extracted."""

  def setUp(self):
    self.test_dir = tempfile.mkdtemp()
    self.als_path = os.path.join(self.test_dir, 'sample_project.als')

  def tearDown(self):
    shutil.rmtree(self.test_dir)

  def _write(self, content):
    with gzip.open(self.als_path, 'wb') as f:
      f.write(content.strip().encode('utf-8'))

  def _audio_track_set(self, sample_ref_xml, devices_xml=''):
    return f"""
        <Ableton MajorVersion="5" MinorVersion="11.0.12">
            <LiveSet>
                <Tracks>
                    <AudioTrack>
                        <DeviceChain>
                            <Devices>{devices_xml}</Devices>
                            <MainSequencer>
                                <ClipSlotList>
                                    <ClipSlot>
                                        <Value>
                                            <AudioClip CurrentStart="0" CurrentEnd="8" Time="0">
                                                <Name Value="Break" />
                                                <IsWarped Value="true" />
                                                <WarpMarkers>
                                                    <WarpMarker SecTime="0" BeatTime="0" />
                                                    <WarpMarker SecTime="1" BeatTime="2" />
                                                </WarpMarkers>
                                                {sample_ref_xml}
                                            </AudioClip>
                                        </Value>
                                    </ClipSlot>
                                </ClipSlotList>
                            </MainSequencer>
                        </DeviceChain>
                    </AudioTrack>
                </Tracks>
            </LiveSet>
        </Ableton>
        """

  def test_modern_file_ref_extraction(self):
    """Live 10/11 style: Path and RelativePath carry a Value attribute."""
    sample_ref = """
        <SampleRef>
          <FileRef>
            <Path Value="C:\\Music\\Samples\\maschine_kick.wav" />
            <RelativePath Value="Samples/Imported/maschine_kick.wav" />
          </FileRef>
          <DefaultDuration Value="88200" />
          <DefaultSampleRate Value="44100" />
        </SampleRef>
        """
    self._write(self._audio_track_set(sample_ref))
    info = parse_als_info(self.als_path)

    self.assertEqual(info['num_samples'], 1)
    sample = info['samples'][0]
    self.assertEqual(sample['name'], 'maschine_kick.wav')
    self.assertEqual(sample['extension'], '.wav')
    self.assertEqual(sample['source'], 'audio_clip')
    self.assertEqual(sample['sample_rate'], 44100)
    # 88200 frames at 44.1kHz is exactly 2 seconds.
    self.assertEqual(sample['duration_sec'], 2.0)

  def test_legacy_file_ref_extraction(self):
    """Older sets store the name separately and the dirs as elements."""
    sample_ref = """
        <SampleRef>
          <FileRef>
            <RelativePath>
              <RelativePathElement Id="1" Dir="Samples" />
              <RelativePathElement Id="2" Dir="Recorded" />
            </RelativePath>
            <Name Value="old_break.aif" />
          </FileRef>
        </SampleRef>
        """
    self._write(self._audio_track_set(sample_ref))
    info = parse_als_info(self.als_path)

    self.assertEqual(info['num_samples'], 1)
    sample = info['samples'][0]
    self.assertEqual(sample['name'], 'old_break.aif')
    self.assertEqual(sample['extension'], '.aif')
    self.assertEqual(sample['relative_path'], 'Samples/Recorded')

  def test_device_nested_sample_extraction(self):
    """Drum racks reference samples from inside the device, not the clip."""
    devices = """
        <OriginalSimpler>
          <Player>
            <MultiSampleMap>
              <SampleParts>
                <MultiSamplePart>
                  <SampleRef>
                    <FileRef>
                      <Path Value="C:\\Music\\Samples\\snare_chop.wav" />
                    </FileRef>
                    <DefaultDuration Value="22050" />
                    <DefaultSampleRate Value="44100" />
                  </SampleRef>
                </MultiSamplePart>
              </SampleParts>
            </MultiSampleMap>
          </Player>
        </OriginalSimpler>
        """
    # No sample on the clip itself, only inside the device.
    self._write(self._audio_track_set('', devices_xml=devices))
    info = parse_als_info(self.als_path)

    self.assertEqual(info['num_samples'], 1)
    sample = info['samples'][0]
    self.assertEqual(sample['name'], 'snare_chop.wav')
    self.assertEqual(sample['source'], 'device')
    self.assertEqual(sample['duration_sec'], 0.5)

    # And the device is classified as an instrument, not an effect.
    device = info['tracks'][0]['devices'][0]
    self.assertEqual(device['kind'], 'instrument')

  def test_audio_clip_emitted_with_warp_markers(self):
    sample_ref = """
        <SampleRef>
          <FileRef><Path Value="/tmp/loop.wav" /></FileRef>
        </SampleRef>
        """
    self._write(self._audio_track_set(sample_ref))
    info = parse_als_info(self.als_path)

    clips = info['tracks'][0]['audio_clips']
    self.assertEqual(len(clips), 1)
    self.assertEqual(clips[0]['name'], 'Break')
    self.assertEqual(clips[0]['warp_markers'], 2)
    self.assertTrue(clips[0]['is_warped'])
    self.assertEqual(clips[0]['sample'], 'loop.wav')
    self.assertEqual(info['num_audio_clips'], 1)

  def test_effect_device_classification(self):
    devices = '<Reverb><UserName Value="Big Hall" /></Reverb>'
    self._write(self._audio_track_set('', devices_xml=devices))
    info = parse_als_info(self.als_path)

    device = info['tracks'][0]['devices'][0]
    self.assertEqual(device['kind'], 'effect')
    self.assertEqual(info['counters']['effects']['Reverb'], 1)


class TestShouldSkipDir(unittest.TestCase):
  """Regression tests for substring-vs-component folder matching."""

  def test_exact_component_is_skipped(self):
    self.assertTrue(
        should_skip_dir(os.path.join('music', 'old', 'proj'), ('old',)))
    self.assertTrue(
        should_skip_dir(os.path.join('a', 'Backup'), ('Backup', 'old')))

  def test_substring_match_does_not_skip(self):
    """'old' is a substring of 'folder', 'Gold' and 'Bold'.

    The previous implementation used `f in dirpath`, which silently
    dropped every project stored under such a directory.
    """
    for name in ('folder', 'Gold', 'Bold', 'Soldier', 'golden hour'):
      path = os.path.join('music', name, 'proj')
      self.assertFalse(should_skip_dir(path, ('old',)),
                       f'{name!r} must not match skip entry "old"')

  def test_unrelated_path_is_kept(self):
    self.assertFalse(
        should_skip_dir(os.path.join('music', 'beats'), tuple(['old'])))


class TestErrorReporting(unittest.TestCase):
  """Parse failures must be counted and logged, never silently dropped."""

  def setUp(self):
    self.test_dir = tempfile.mkdtemp()

  def tearDown(self):
    shutil.rmtree(self.test_dir)

  def test_corrupt_project_is_logged(self):
    bad_path = os.path.join(self.test_dir, 'broken.als')
    with open(bad_path, 'wb') as f:
      f.write(b'this is not gzipped xml')

    with self.assertLogs('parse_projects', level='ERROR') as captured:
      result = load_projects_in_dir(self.test_dir)

    self.assertEqual(result, {})
    self.assertTrue(
        any('broken.als' in line for line in captured.output),
        f'expected the failing path in the log, got {captured.output}')

  def test_valid_and_invalid_mix(self):
    bad_path = os.path.join(self.test_dir, 'broken.als')
    with open(bad_path, 'wb') as f:
      f.write(b'not gzip')

    good_path = os.path.join(self.test_dir, 'good.als')
    with gzip.open(good_path, 'wb') as f:
      f.write(b'<Ableton MinorVersion="11.0.0"><LiveSet><Tracks/>'
              b'</LiveSet></Ableton>')

    with self.assertLogs('parse_projects', level='ERROR'):
      result = load_projects_in_dir(self.test_dir)

    # The good project still lands even though a sibling failed.
    self.assertIn('good', result)
    self.assertNotIn('broken', result)


class TestVstPresetExtraction(unittest.TestCase):
  """Recovery of readable state from opaque VST plugin chunks."""

  # Modelled on a real Maschine 2 chunk: length-prefixed strings with
  # serialization scaffolding interleaved between useful values.
  MASCHINE_BLOB = (b'\x00\x01' + b'serialization::archive' + b'\x00' +
                   b'Kick AR60sLate V98 1' + b'\x00' +
                   b'NI::MASCHINE::DATA::Sampler' + b'\x00' +
                   b',Samples/Drums/Kick/Kick AR60sLate V108 1.wav' + b'\x00' +
                   b' /Users/Shared/Maschine 2 Library' + b'\x00' +
                   b'Maschine 2 Factory Library' + b'\x00' +
                   b'.Samples/Drums/Snare/Snare AR60sLate V117 1.wav' + b'\x00')

  def test_extracts_internal_sample_paths(self):
    preset = LiveSetVstPresetData(self.MASCHINE_BLOB.hex())
    self.assertIn('Samples/Drums/Kick/Kick AR60sLate V108 1.wav',
                  preset.sample_paths)
    self.assertIn('Samples/Drums/Snare/Snare AR60sLate V117 1.wav',
                  preset.sample_paths)
    # Bare filenames make the samples searchable.
    self.assertIn('Kick AR60sLate V108 1.wav', preset.sample_names)

  def test_extracts_library_names(self):
    preset = LiveSetVstPresetData(self.MASCHINE_BLOB.hex())
    self.assertTrue(
        any('Factory Library' in lib for lib in preset.libraries),
        f'expected a library entry, got {preset.libraries}')

  def test_recovers_pad_name(self):
    preset = LiveSetVstPresetData(self.MASCHINE_BLOB.hex())
    self.assertIn('Kick AR60sLate V98 1', preset.preset_names)

  def test_filters_serialization_noise(self):
    preset = LiveSetVstPresetData(self.MASCHINE_BLOB.hex())
    self.assertNotIn('serialization::archive', preset.preset_names)
    self.assertFalse(
        any(name.startswith('NI::') for name in preset.preset_names),
        f'internal keys leaked into names: {preset.preset_names}')

  def test_utf16_strings_are_recovered(self):
    blob = 'Maschine Expansion Pack'.encode('utf-16-le')
    preset = LiveSetVstPresetData(blob.hex())
    self.assertTrue(
        any('Expansion' in lib for lib in preset.libraries),
        f'expected UTF-16 text to be decoded, got {preset.libraries}')

  def test_malformed_input_is_safe(self):
    for bad in ('', 'zzzz', 'abc'):  # empty, non-hex, odd length
      preset = LiveSetVstPresetData(bad)
      self.assertEqual(preset.sample_paths, [])
      self.assertEqual(preset.byte_size, 0 if bad != 'abc' else 1)


class TestPresetNameFilter(unittest.TestCase):
  """Rejection of binary noise masquerading as preset names.

  Every string below was observed verbatim in the `vst_strings` counter
  on real data, where it accounted for roughly 95% of all values.
  """

  def assert_rejected(self, value):
    self.assertFalse(
        LiveSetVstPresetData._is_plausible_name(value),
        f'binary noise leaked through the filter: {value!r}')

  def assert_kept(self, value):
    self.assertTrue(
        LiveSetVstPresetData._is_plausible_name(value),
        f'a real preset name was wrongly dropped: {value!r}')

  def test_rejects_byte_reversed_chunk_ids(self):
    # 'data' and 'zlibinfo' read backwards out of little-endian fields.
    for value in ("'atad", 'atad', 'ofnibilz', 'zlibinfo'):
      self.assert_rejected(value)

  def test_rejects_magic_id_with_stray_byte(self):
    # 'NISD' plus one trailing byte from the surrounding binary.
    for suffix in 'ejlmstvy':
      self.assert_rejected(f'DSIN{suffix}')

  def test_rejects_guids_and_hex_digests(self):
    for value in ('EC4D6957-197C-E311-937A-F0DEF1BE55590',
                  'EDD1B3D9-C009-42E7-A0B0-8B14640585880',
                  'F512EFBC-7E1B-4D58-AB66-C5E57BE5698B0'):
      self.assert_rejected(value)

  def test_rejects_embedded_config_fragments(self):
    for value in ('midiMap = {', 'parameters = {',
                  'name = "Noise Amount",',
                  'Applied Acoustics Systems:VST:INSTR:1280072244'):
      self.assert_rejected(value)

  def test_rejects_random_byte_runs(self):
    for value in ('UU7C{ksA', 'JD!r E', 'gAHH ?', 'cb``'):
      self.assert_rejected(value)

  def test_rejects_internal_keys(self):
    for value in ('#NI#CS#Document#', 'NI::SOUND::Document',
                  'serialization::archive'):
      self.assert_rejected(value)

  def test_rejects_marker_with_trailing_byte(self):
    # 'ofnibilzD' survived an earlier, weaker version of this filter.
    for value in ('ofnibilzD', 'zlibinfoX', 'documentA'):
      self.assert_rejected(value)

  def test_rejects_encoded_patch_data(self):
    # Zebra2 emits long unbroken base64-like runs of patch state.
    for value in (
        'lcjiWTlcfmombiAohkdglbmaeA6tIA10eiSHGhcKglLgoHdeHfcKRQRLcogiThaA',
        'mUApideJA3HmbScjhopoadcjcnkbplUPalpoUgimoNGAhchhcoAhchhcoFLfodko',
        'qwA1K1A1iaKA1UKA1maKA1oaKtAacA5qA3qwA1K1A1iaKA1UKA1maKA1oaKA2FA1',
    ):
      self.assert_rejected(value)

  def test_keeps_real_preset_names(self):
    for value in ('Default', 'added punch comp', 'Kick AR60sLate V98 1',
                  'Snare Buck50 1', 'Warm Master', 'Vintage Tape Delay',
                  "Jake's Lead Tone", 'Drum Bus Glue 2',
                  'Queensbridge Story', 'Alloy 1', 'Pitch Shift',
                  'Side-Chain', 'Charactr', 'Tremolo', 'Mix Glue'):
      self.assert_kept(value)


class TestSampleKitGrouping(unittest.TestCase):
  """Plugin-internal samples collapse to one entry per kit folder."""

  def _preset_with_paths(self, paths):
    preset = LiveSetVstPresetData('')
    preset.sample_paths = list(paths)
    return preset

  def test_groups_by_containing_folder(self):
    preset = self._preset_with_paths([
        'Samples/Drums/Kick/a.wav',
        'Samples/Drums/Kick/b.wav',
        'Samples/Drums/Snare/c.wav',
    ])
    kits = preset.sample_kits()
    self.assertEqual(len(kits), 2)
    # Sorted by descending count, so the two-sample kit comes first.
    self.assertEqual(kits[0]['path'], 'Samples/Drums/Kick')
    self.assertEqual(kits[0]['count'], 2)
    self.assertEqual(kits[0]['samples'], ['a.wav', 'b.wav'])
    self.assertEqual(kits[1]['path'], 'Samples/Drums/Snare')
    self.assertEqual(kits[1]['count'], 1)

  def test_normalizes_windows_separators(self):
    preset = self._preset_with_paths(
        ['Samples\\Drums\\Kick\\a.wav', 'Samples/Drums/Kick/b.wav'])
    kits = preset.sample_kits()
    self.assertEqual(len(kits), 1, f'separators not normalized: {kits}')
    self.assertEqual(kits[0]['count'], 2)

  def test_path_without_folder_is_labelled(self):
    preset = self._preset_with_paths(['loose.wav'])
    kits = preset.sample_kits()
    self.assertEqual(kits[0]['path'], UNKNOWN_KIT)

  def test_respects_caps(self):
    preset = self._preset_with_paths(
        [f'Kit{i}/s.wav' for i in range(50)])
    self.assertEqual(len(preset.sample_kits(max_kits=10)), 10)

    crowded = self._preset_with_paths(
        [f'Kit/s{i}.wav' for i in range(50)])
    kit = crowded.sample_kits(max_names_per_kit=5)[0]
    # The cap limits the listing, not the reported total.
    self.assertEqual(len(kit['samples']), 5)
    self.assertEqual(kit['count'], 50)

  def test_as_dict_is_concise_by_default(self):
    preset = self._preset_with_paths(
        ['Samples/Drums/Kick/a.wav', 'Samples/Drums/Kick/b.wav'])
    info = preset.as_dict()
    self.assertNotIn('sample_paths', info)
    self.assertEqual(info['sample_count'], 2)
    self.assertEqual(len(info['sample_kits']), 1)

  def test_as_dict_can_restore_full_paths(self):
    paths = ['Samples/Drums/Kick/a.wav', 'Samples/Drums/Kick/b.wav']
    info = self._preset_with_paths(paths).as_dict(full_paths=True)
    self.assertEqual(info['sample_paths'], paths)


class TestSampleCategory(unittest.TestCase):
  """Sample categories derived from folder conventions."""

  def test_recognises_each_convention(self):
    cases = {
        'Samples/Processed/Crop/chop 1.wav': 'crop',
        'Samples/Processed/Consolidate/a.wav': 'consolidate',
        'Samples/Processed/Reverse/b.wav': 'reverse',
        'Samples/Processed/Freeze/c.wav': 'freeze',
        'Samples/Loops/Drum Loops/HIP HOP/d.wav': 'loop',
        'Samples/Imported/e.wav': 'imported',
        'Samples/Recorded/f.wav': 'recorded',
    }
    for path, expected in cases.items():
      self.assertEqual(classify_sample_path(path), expected, path)

  def test_specific_processed_folder_wins(self):
    # Must not fall back to the generic 'processed' label.
    self.assertEqual(
        classify_sample_path('Samples/Processed/Crop/x.wav'), 'crop')
    # A Processed folder with no known subfolder still classifies.
    self.assertEqual(
        classify_sample_path('Samples/Processed/x.wav'), 'processed')

  def test_matches_whole_components_only(self):
    # 'Crop' must not match inside 'Cropped Ideas', and the sample is
    # not under any known convention, so it stays unclassified.
    self.assertIsNone(
        classify_sample_path('Samples/Cropped Ideas/x.wav'))
    self.assertIsNone(classify_sample_path('Samples/Bloops/x.wav'))

  def test_handles_windows_separators_and_case(self):
    self.assertEqual(
        classify_sample_path('Samples\\PROCESSED\\Crop\\x.wav'), 'crop')

  def test_unknown_and_empty_paths(self):
    self.assertIsNone(classify_sample_path('Samples/Other/x.wav'))
    self.assertIsNone(classify_sample_path(''))
    self.assertIsNone(classify_sample_path(None))


if __name__ == '__main__':
  unittest.main()
