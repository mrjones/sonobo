import json
import unittest
import unittest.mock

import sonobo

class FakeCoordinator:
    playing = False

    def get_current_transport_info(self):
        return {'current_transport_state': 'PLAYING' if self.playing else 'STOPPED'}

    def play(self):
        self.playing = True

    def pause(self):
        self.playing = False

class FakeGroup:
    coordinator = FakeCoordinator()

class FakeSpeaker:
    group = FakeGroup()

class TestSonobo(unittest.TestCase):
    def test_foo(self):
        songmap_string = """[
   {
        "debugName": "Atencion Atencion - Que Pasa Con La Music",
        "key": "A",
        "kind": "SPOTIFY",
        "payload": "https://open.spotify.com/album/6gTdDnREfXIGjEKqfsBWPi?si=9N6YIv0UTluLn01_ZkMyMg"
    }
]"""

        speaker = FakeSpeaker
        speaker.group.coordinator.play = unittest.mock.MagicMock(wraps=speaker.group.coordinator.play)
        speaker.group.coordinator.pause = unittest.mock.MagicMock(wraps=speaker.group.coordinator.pause)

        songmap_json = json.loads(songmap_string)
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

if __name__ == '__main__':
    unittest.main()
