# TODO
# - Webserver UI for editing songmap.json
# - Logs to Webserver UI
# - try-catch / error recovery
# - Support multi-room joining

import json
import soco
from soco.plugins.sharelink import ShareLinkPlugin
import struct


EVENT_DEVICE_PATH = '/dev/input/by-id/usb-Telink_Wireless_Receiver-if01-event-kbd'

KEY_STRING_TO_CODE_MAP = {
    '1': 2,
    '2': 3,
    '3': 4,
    '4': 5,
    '5': 6,
    '6': 7,
    '7': 8,
    '8': 9,
    '9': 10,
    '0': 11,

    'Q': 16,
    'W': 17,
    'E': 18,
    'R': 19,
    'T': 20,
    'Y': 21,
    'U': 22,
    'I': 23,
    'O': 24,
    'P': 25,

    'A': 30,
    'S': 31,
    'D': 32,
    'F': 33,
    'G': 34,
    'H': 35,
    'J': 36,
    'K': 37,
    'L': 38,

    'Z': 44,
    'X': 45,
    'C': 46,
    'V': 47,
    'B': 48,
    'N': 49,
    'M': 50,
}

class SongInfo:
    url: str
    kind: str

    def __init__(self, payload: str, kind: str):
        self.payload = payload
        self.kind = kind

    def __repr__(self):
        return '<SongInfo kind=%s payload=%s>' % (self.kind, self.payload)

class Sonobo:
    key_code_to_song_map: dict[str, SongInfo] = {}
    speaker = None

    def __init__(self, key_code_to_song_map: dict[str, SongInfo], speaker):
        self.key_code_to_song_map = key_code_to_song_map
        self.speaker = speaker

    def coordinator(self):
        return self.speaker.group.coordinator

    def loop(self):
        print('opening "%s"' % (EVENT_DEVICE_PATH))
        with open(EVENT_DEVICE_PATH, 'rb') as f:
            while True:
                # https://www.kernel.org/doc/Documentation/input/input.txt
                #
                # Section5: Event interfaces
                #
                # You can use blocking and nonblocking reads, also select() on the
                # /dev/input/eventX devices, and you'll always get a whole number of input
                # events on a read. Their layout is:
                #
                # struct input_event {
                #	struct timeval time;
                #	unsigned short type;
                #	unsigned short code;
                #	unsigned int value;
                # };
                #
                # 'struct timeval' is from <sys/time.h> and is:
                # struct timeval {
                #	long	tv_sec;		/* seconds */
                #	long	tv_usec;	/* and microseconds */
                # };

                struct_format = 'llHHi'  # long, long, short, short, int
                size = struct.calcsize(struct_format)
                data = f.read(size)

                _tv_sec, _tv_usec, typet, code, value = struct.unpack(struct_format, data)

                # 'time' is the timestamp, it returns the time at which the event happened.
                # Type is for example EV_REL for relative moment, EV_KEY for a keypress or
                # release. More types are defined in include/uapi/linux/input-event-codes.h.
                #
                # 'code' is event code, for example REL_X or KEY_BACKSPACE, again a complete
                # list is in include/uapi/linux/input-event-codes.h.
                #
                # 'value' is the value the event carries. Either a relative change for
                # EV_REL, absolute new value for EV_ABS (joysticks ...), or 0 for EV_KEY for
                # release, 1 for keypress and 2 for autorepeat.
                #
                # https://github.com/torvalds/linux/blob/master/include/uapi/linux/input-event-codes.h
                EV_KEY = 0x01
                KEY_UP = 103
                KEY_DOWN = 108
                KEY_LEFT = 105
                KEY_RIGHT = 106
                KEY_SPACE = 57
                KEY_BACKSPACE = 14

                KEY_F12 = 88

                if typet == EV_KEY and value == 1:
                    # Keypress
                    print("%d pressed" % (code))
                    if code == KEY_BACKSPACE:
                        print("Pause")
                        self.coordinator().pause();
                    if code == KEY_SPACE:
                        if self.coordinator().get_current_transport_info()['current_transport_state'] != 'PLAYING':
                            print("Play")
                            self.coordinator().play()
                        else:
                            print("Pause")
                            self.coordinator().pause()
                    elif code == KEY_BACKSPACE:
                        print("Pause")
                        self.coordinator().pause()
                    elif code == KEY_UP:
                        current_vol = self.coordinator().volume
                        print("Volume up (@%d)" % current_vol)
                        if self.coordinator().volume > 15:
                            print("Volume capped")
                        else:
                            self.coordinator().set_relative_volume(2)
                    elif code == KEY_DOWN:
                        print("Volume down")
                        self.coordinator().set_relative_volume(-2)
                    elif code == KEY_RIGHT:
                        print("Next")
                        self.coordinator().next()
                    elif code == KEY_LEFT:
                        print("Previous")
                        self.coordinator().previous()
                    elif code == KEY_F12:
                        print("Dumping Sonos Playlist IDs")
                        for playlist in self.coordinator().get_sonos_playlists():
                            print("title=%s item_id=%s" % (playlist.title, playlist.item_id))
                    elif code in self.key_code_to_song_map:
                        song: SongInfo = self.key_code_to_song_map[code];
                        print('Song %s' % song)
                        if song.kind == 'SPOTIFY':
                            self.coordinator().clear_queue()
                            living_room_sharelink = ShareLinkPlugin(self.coordinator())
                            living_room_sharelink.add_share_link_to_queue(song.payload)
                            self.coordinator().play()
                        elif song.kind == 'SONOS_PLAYLIST_NAME':
                            playlist = self.coordinator().get_sonos_playlist_by_attr(
                                'title', song.payload)
                            self.coordinator().clear_queue()
                            self.coordinator().add_to_queue(playlist);
                            self.coordinator().play()
                        else:
                            print('unknown song kind: %s' % song.kind)


def speaker_with_name(speakers, name):
    for speaker in speakers:
        if speaker.player_name == name:
            return speaker
    raise ValueError('Could not find speaker with name "%s"' % name)

def read_key_code_to_song_map() -> dict[str, SongInfo]:
    songmap_contents = open('songmap.json')

    key_strings_and_songs = json.load(songmap_contents)
    key_code_to_song_map = {}
    for song in key_strings_and_songs:
        key_code_to_song_map[KEY_STRING_TO_CODE_MAP[song['key']]] = SongInfo(song['payload'], song['kind'])

    return key_code_to_song_map

def main():
    print("discovering sonos...")
    speakers = soco.discover()

    key_code_to_song_map = read_key_code_to_song_map();
    print(key_code_to_song_map);

    for speaker in speakers:
        print(" - %s" % (speaker.player_name))

    living_room_speaker = speaker_with_name(speakers, 'Living Room')

    sonobo = Sonobo(key_code_to_song_map, living_room_speaker);
    sonobo.loop()

    print("Done.")

if __name__ == "__main__":
    main()
