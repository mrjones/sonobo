import json
import logging
import sys
import unittest
import unittest.mock

import sonobo

logger = logging.getLogger()
logger.level = logging.DEBUG
stream_handler = logging.StreamHandler(sys.stdout)
logger.addHandler(stream_handler)

class FakeAvTransport:
    def AddURIToQueue(self):
        pass

class FakeCoordinator:
    playing = False
    volume = 10

    def __init__(self):
        self.playing = False
        self.avTransport = FakeAvTransport()

    def get_current_transport_info(self):
        return {'current_transport_state': 'PLAYING' if self.playing else 'STOPPED'}

    def play(self):
        self.playing = True

    def pause(self):
        self.playing = False

    def clear_queue(self):
        pass

    def set_relative_volume(self, delta):
        self.volume = self.volume + delta

class FakeGroup:
    def __init__(self):
        self.coordinator = FakeCoordinator()


class FakeSpeaker:
    def __init__(self):
        self.group = FakeGroup()

ONE_SONG_RAW_SONG_MAP = """[
   {
        "debugName": "Atencion Atencion - Que Pasa Con La Music",
        "key": "A",
        "kind": "SPOTIFY",
        "payload": "https://open.spotify.com/track/payload"
    }
]"""

class TestSonobo(unittest.TestCase):
    def test_play_from_song_map(self):
        speaker = FakeSpeaker()
        speaker.group.coordinator.clear_queue = unittest.mock.MagicMock()
        speaker.group.coordinator.avTransport.AddURIToQueue = unittest.mock.MagicMock()
        speaker.group.coordinator.play = unittest.mock.MagicMock(wraps=speaker.group.coordinator.play)

        songmap_json = json.loads(ONE_SONG_RAW_SONG_MAP)
        s = sonobo.Sonobo(songmap_json, speaker)

        s.dispatch(sonobo.EV_KEY, sonobo.KEY_STRING_TO_CODE_MAP['A'], 1)

        speaker.group.coordinator.clear_queue.assert_called_once()
        speaker.group.coordinator.avTransport.AddURIToQueue.assert_called_once()  ## XXX Get URL
        speaker.group.coordinator.play.assert_called_once()

    def test_play_pause(self):
        speaker = FakeSpeaker()
        speaker.group.coordinator.play = unittest.mock.MagicMock(wraps=speaker.group.coordinator.play)
        speaker.group.coordinator.pause = unittest.mock.MagicMock(wraps=speaker.group.coordinator.pause)

        songmap_json = json.loads(ONE_SONG_RAW_SONG_MAP)
        s = sonobo.Sonobo(songmap_json, speaker)

        s.dispatch(sonobo.EV_KEY, sonobo.KEY_SPACE, 1)
        speaker.group.coordinator.play.assert_called_once()
        speaker.group.coordinator.pause.assert_not_called()

        s.dispatch(sonobo.EV_KEY, sonobo.KEY_SPACE, 1)
        speaker.group.coordinator.pause.assert_called_once()

        speaker.group.coordinator.play.reset_mock()

        speaker.group.coordinator.play.assert_not_called()
        s.dispatch(sonobo.EV_KEY, sonobo.KEY_SPACE, 1)
        speaker.group.coordinator.play.assert_called_once()
        speaker.group.coordinator.pause.assert_called_once()

    def test_volume(self):
        speaker = FakeSpeaker()
        songmap_json = json.loads(ONE_SONG_RAW_SONG_MAP)
        s = sonobo.Sonobo(songmap_json, speaker)

        for _ in range(25):
            s.dispatch(sonobo.EV_KEY, sonobo.KEY_UP, 1)

        self.assertEqual(sonobo.MAX_VOLUME, speaker.group.coordinator.volume,
                         "Volume should be capped at MAX_VOLUME")

        s.dispatch(sonobo.EV_KEY, sonobo.KEY_DOWN, 1)

        self.assertTrue(speaker.group.coordinator.volume < sonobo.MAX_VOLUME,
                        "Volume (%d) should be lower than MAX_VOLUME (%s)"
                        % (speaker.group.coordinator.volume, sonobo.MAX_VOLUME))

        for _ in range(25):
            s.dispatch(sonobo.EV_KEY, sonobo.KEY_DOWN, 1)

        self.assertEqual(0, speaker.group.coordinator.volume,
                         "Min volume should be capped at 0")

if __name__ == '__main__':
    unittest.main()
