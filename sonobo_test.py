import json
import logging
import sys
import unittest
import unittest.mock
import urllib.parse

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

class FakeClock(sonobo.Clock):
    def __init__(self):
        self.current_timestamp = 0.0

    def advance(self, delta):
        self.current_timestamp = self.current_timestamp + delta

    def now_ts(self):
        return self.current_timestamp

class TestSonobo(unittest.TestCase):
    def setUp(self):
        self.fake_clock = FakeClock()

    def enqueue_args_as_dict(self, call_args):
        args_dict = {}
        for key in call_args.args[0]:
            k, v = key
            args_dict[k] = v
            print("ARGGG %s=%s" % (k, v))
        return args_dict

    def test_play_from_song_map(self):
        speaker = FakeSpeaker()
        speaker.group.coordinator.clear_queue = unittest.mock.MagicMock()
        speaker.group.coordinator.avTransport.AddURIToQueue = unittest.mock.MagicMock()
        speaker.group.coordinator.play = unittest.mock.MagicMock(wraps=speaker.group.coordinator.play)

        songmap_json = json.loads(ONE_SONG_RAW_SONG_MAP)
        s = sonobo.Sonobo(songmap_json, speaker, self.fake_clock)

        s.dispatch(sonobo.EV_KEY, sonobo.KEY_STRING_TO_CODE_MAP['A'], 1, 0.0)

        speaker.group.coordinator.clear_queue.assert_called_once()
        speaker.group.coordinator.avTransport.AddURIToQueue.assert_called_once()
        self.assertEqual(
            urllib.parse.quote_plus('spotify:track:payload').lower(),
            self.enqueue_args_as_dict(speaker.group.coordinator.avTransport.AddURIToQueue.call_args)['EnqueuedURI'])
        speaker.group.coordinator.play.assert_called_once()

    def test_dedupe_fast_repeats(self):
        speaker = FakeSpeaker()
        speaker.group.coordinator.clear_queue = unittest.mock.MagicMock()
        speaker.group.coordinator.avTransport.AddURIToQueue = unittest.mock.MagicMock()
        speaker.group.coordinator.play = unittest.mock.MagicMock(wraps=speaker.group.coordinator.play)

        songmap_json = json.loads(ONE_SONG_RAW_SONG_MAP)
        s = sonobo.Sonobo(songmap_json, speaker, self.fake_clock)

        # Press A twice, with a delay just under the threshold
        s.dispatch(sonobo.EV_KEY, sonobo.KEY_STRING_TO_CODE_MAP['A'], 1, 0.0)
        self.fake_clock.advance(sonobo.FAST_REPEAT_THRESHOLD_SEC + 1.0)
        s.dispatch(sonobo.EV_KEY, sonobo.KEY_STRING_TO_CODE_MAP['A'], 1, 3.9)

        self.assertEqual(1, speaker.group.coordinator.avTransport.AddURIToQueue.call_count)

        self.fake_clock.advance(sonobo.FAST_REPEAT_THRESHOLD_SEC - 1.0)
        s.dispatch(sonobo.EV_KEY, sonobo.KEY_STRING_TO_CODE_MAP['A'], 1, 8.0)
        self.assertEqual(2, speaker.group.coordinator.avTransport.AddURIToQueue.call_count)

    def test_play_pause(self):
        speaker = FakeSpeaker()
        speaker.group.coordinator.play = unittest.mock.MagicMock(wraps=speaker.group.coordinator.play)
        speaker.group.coordinator.pause = unittest.mock.MagicMock(wraps=speaker.group.coordinator.pause)

        songmap_json = json.loads(ONE_SONG_RAW_SONG_MAP)
        s = sonobo.Sonobo(songmap_json, speaker, self.fake_clock)

        s.dispatch(sonobo.EV_KEY, sonobo.KEY_SPACE, 1, 0.0)
        speaker.group.coordinator.play.assert_called_once()
        speaker.group.coordinator.pause.assert_not_called()

        s.dispatch(sonobo.EV_KEY, sonobo.KEY_SPACE, 1, 0.0)
        speaker.group.coordinator.pause.assert_called_once()

        speaker.group.coordinator.play.reset_mock()

        speaker.group.coordinator.play.assert_not_called()
        s.dispatch(sonobo.EV_KEY, sonobo.KEY_SPACE, 1, 0.0)
        speaker.group.coordinator.play.assert_called_once()
        speaker.group.coordinator.pause.assert_called_once()

    def test_volume(self):
        speaker = FakeSpeaker()
        songmap_json = json.loads(ONE_SONG_RAW_SONG_MAP)
        s = sonobo.Sonobo(songmap_json, speaker, self.fake_clock)

        for _ in range(25):
            s.dispatch(sonobo.EV_KEY, sonobo.KEY_UP, 1, 0.0)

        self.assertEqual(sonobo.MAX_VOLUME, speaker.group.coordinator.volume,
                         "Volume should be capped at MAX_VOLUME")

        s.dispatch(sonobo.EV_KEY, sonobo.KEY_DOWN, 1, 0.0)

        self.assertTrue(speaker.group.coordinator.volume < sonobo.MAX_VOLUME,
                        "Volume (%d) should be lower than MAX_VOLUME (%s)"
                        % (speaker.group.coordinator.volume, sonobo.MAX_VOLUME))

        for _ in range(25):
            s.dispatch(sonobo.EV_KEY, sonobo.KEY_DOWN, 1, 0.0)

        self.assertEqual(0, speaker.group.coordinator.volume,
                         "Min volume should be capped at 0")

    def test_change_song_map(self):
        speaker = FakeSpeaker()
        original_songmap = json.loads(ONE_SONG_RAW_SONG_MAP)
        s = sonobo.Sonobo(original_songmap, speaker, self.fake_clock)

        speaker.group.coordinator.clear_queue = unittest.mock.MagicMock()
        speaker.group.coordinator.avTransport.AddURIToQueue = unittest.mock.MagicMock()
        speaker.group.coordinator.play = unittest.mock.MagicMock(wraps=speaker.group.coordinator.play)

        s.dispatch(sonobo.EV_KEY, sonobo.KEY_STRING_TO_CODE_MAP['A'], 1, 0.0)

        speaker.group.coordinator.clear_queue.assert_called_once()
        speaker.group.coordinator.avTransport.AddURIToQueue.assert_called_once()

        self.assertEqual(
            urllib.parse.quote_plus('spotify:track:payload').lower(),
            self.enqueue_args_as_dict(speaker.group.coordinator.avTransport.AddURIToQueue.call_args)['EnqueuedURI'])
        speaker.group.coordinator.play.assert_called_once()


        NEW_SONG_MAP = """[
   {
        "debugName": "NEW SONG",
        "key": "A",
        "kind": "SPOTIFY",
        "payload": "https://open.spotify.com/track/new_payload"
    }
]"""

        self.fake_clock.advance(sonobo.FAST_REPEAT_THRESHOLD_SEC + 1.0)

        # Change the song map and assert the new url is enqueued when we press the same key:

        s.update_code_to_song_map(json.loads(NEW_SONG_MAP))

        speaker.group.coordinator.avTransport.AddURIToQueue.reset_mock()

        s.dispatch(sonobo.EV_KEY, sonobo.KEY_STRING_TO_CODE_MAP['A'], 1, 5.0)

        speaker.group.coordinator.avTransport.AddURIToQueue.assert_called_once()
        self.assertEqual(
            urllib.parse.quote_plus('spotify:track:new_payload').lower(),
            self.enqueue_args_as_dict(speaker.group.coordinator.avTransport.AddURIToQueue.call_args)['EnqueuedURI'])

if __name__ == '__main__':
    unittest.main()
