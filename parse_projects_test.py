
import datetime
import gzip
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from parse_projects import parse_als_info


class TestParseProjects(unittest.TestCase):

  def setUp(self):
    self.test_dir = tempfile.mkdtemp()
    self.als_path = os.path.join(self.test_dir, 'test_project.als')

  def tearDown(self):
    shutil.rmtree(self.test_dir)

  def create_mock_als(self, content):
    with gzip.open(self.als_path, 'wb') as f:
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
            </LiveSet>
        </Ableton>
        """
    self.create_mock_als(xml_content.strip())

    info = parse_als_info(self.als_path, include_midi_clips=True)
    self.assertEqual(info['ableton_version_full'], '11.0.12')
    self.assertEqual(info['tempo'], 120.0)
    self.assertEqual(info['scale_root'], 'C')
    self.assertEqual(info['scale_name'], 'Major')
    # Duration: Clip 0-4 beats @ 120bpm = 4 beats / 2 beats/sec = 2 seconds
    self.assertEqual(info['duration_sec'], 2.0)

    self.assertEqual(info['time_signature'], '65540')  # 4/4 decoded or raw
    expected_time = datetime.datetime.fromtimestamp(1672574400).strftime('%Y-%m-%d %H:%M:%S')
    self.assertEqual(info['created'], expected_time)
    self.assertEqual(len(info['tracks']), 2)  # MidiTrack + MasterTrack

    # Check plugin extraction
    midi_track = info['tracks'][0]
    self.assertEqual(len(midi_track['devices']), 1)
    self.assertEqual(midi_track['devices'][0]['preset'], 'Sylenth1')

    # Check clip extraction
    self.assertEqual(len(midi_track['midi_clips']), 1)
    self.assertEqual(midi_track['midi_clips'][0]['name'], 'Test Clip')


if __name__ == '__main__':
  unittest.main()
