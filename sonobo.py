# TODO
# - Webserver UI for editing songmap.json
# - Logs to Webserver UI
# - try-catch / error recovery
# - Support multi-room joining

import cgi
import datetime
import http.server
import json
import shutil
import struct
import threading
import time
import typing
import typing_extensions
import urllib.parse

import soco # type: ignore
import soco.plugins.sharelink # type: ignore

EVENT_DEVICE_PATH = '/dev/input/by-id/usb-Telink_Wireless_Receiver-if01-event-kbd'

EV_KEY = 0x01
KEY_UP = 103
KEY_DOWN = 108
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_SPACE = 57
KEY_BACKSPACE = 14

KEY_F12 = 88

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

JsonSongT = typing_extensions.TypedDict('JsonSongT', {'debugName': str, 'key': str, 'payload': str, 'kind': str})

class SongInfo:
    url: str
    kind: str

    def __init__(self, payload: str, kind: str):
        self.payload = payload
        self.kind = kind

    def __repr__(self) -> str:
        return '<SongInfo kind=%s payload=%s>' % (self.kind, self.payload)

class Sonobo:
    songmap_json: list[JsonSongT] = []
    key_code_to_song_map: dict[int, SongInfo] = {}
    mutex = threading.Lock()
    speaker = None

    last_key = None
    last_key_timestamp = None

    def __init__(self, songmap_json, speaker):
        self.songmap_json = songmap_json
        self.key_code_to_song_map = songmap_json_to_map(songmap_json)
        self.speaker = speaker
        self.last_key = -1
        self.last_key_timestamp = datetime.datetime.min

    def get_songmap_json(self) -> list[JsonSongT]:
        self.mutex.acquire()
        try:
            return self.songmap_json
        finally:
            self.mutex.release()

    def song_for_code(self, code: int) -> typing.Optional[SongInfo]:
        self.mutex.acquire()
        try:
            if code in self.key_code_to_song_map:
                return self.key_code_to_song_map[code]
            return None
        finally:
            self.mutex.release()

    def update_code_to_song_map(self, songmap_json: list[JsonSongT]) -> None:
        code_to_song_map = songmap_json_to_map(songmap_json)
        print("Received new code-to-song map with %d songs" % (len(code_to_song_map)))
        for item in code_to_song_map.items():
            print(item)
        self.mutex.acquire()
        try:
            self.songmap_json = songmap_json
            self.key_code_to_song_map = code_to_song_map
        finally:
            self.mutex.release()

    def coordinator(self):
        return self.speaker.group.coordinator

    def get_keypress(self, keyboard_dev_file: typing.BinaryIO) -> typing.Tuple[int, int, int]:
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
        data = keyboard_dev_file.read(size)

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
        # https://github.com/torvalds/linux/blob/master/include/uapi/linux/input-event-codes

        return (typet, code, value)

    def dispatch(self, typet: int, code: int, value: int) -> None:
        if typet == EV_KEY and value == 1:
            # Keypress
            print("%d pressed" % (code))
            fast_repeat = False
            if self.last_key == code and self.last_key_timestamp is not None:
                delay = datetime.datetime.now() - self.last_key_timestamp
                if delay.total_seconds() < 2.0:
                    fast_repeat = True

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
                print("=== Dumping Sonos Playlist IDs ===")
                for playlist in self.coordinator().get_sonos_playlists():
                    print("title=%s item_id=%s" % (playlist.title, playlist.item_id))
            elif song := self.song_for_code(code):
                if fast_repeat:
                    print("Ignoring fast-repeat of %d" % code)
                else:
                    print('Song %s' % song)
                    if song.kind == 'SPOTIFY':
                        self.coordinator().clear_queue()
                        living_room_sharelink = soco.plugins.sharelink.ShareLinkPlugin(self.coordinator())
                        living_room_sharelink.add_share_link_to_queue(song.payload)
                        self.coordinator().play()
                    elif song.kind == 'SONOS_PLAYLIST_NAME':
                        playlist = self.coordinator().get_sonos_playlist_by_attr(
                            'title', song.payload)
                        self.coordinator().clear_queue()
                        self.coordinator().add_to_queue(playlist)
                        self.coordinator().play()
                    else:
                        print('unknown song kind: %s' % song.kind)

            self.last_key = code
            self.last_key_timestamp = datetime.datetime.now()

    def loop(self) -> None:
        print('opening "%s"' % (EVENT_DEVICE_PATH))
        with open(EVENT_DEVICE_PATH, 'rb') as f:
            print('READY')
            while True:
                try:
                    typet, code, value = self.get_keypress(f)
                    self.dispatch(typet, code, value)
                except Exception as e:
                    print("===== EXCEPTION: ", datetime.datetime.now(), " =====")
                    print(type(e))
                    print(e.args)
                    print(e)

def speaker_with_name(speakers, name):
    for speaker in speakers:
        if speaker.player_name == name:
            return speaker
    raise ValueError('Could not find speaker with name "%s"' % name)

def songmap_json_to_map(json_songmap_contents: list[JsonSongT]) -> dict[int, SongInfo]:
    key_code_to_song_map = {}
    for song in json_songmap_contents:
        key_code_to_song_map[KEY_STRING_TO_CODE_MAP[song['key']]] = SongInfo(song['payload'], song['kind'])
    return key_code_to_song_map


class SonoboHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, sonobo: Sonobo, *args):
        self.sonobo = sonobo
        self.json_songmap: typing.Optional[list[JsonSongT]] = None
        super().__init__(*args)

    def do_GET(self) -> None:
        print('do_GET')
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(("<html><body><form method=POST action=/updatesongmap><textarea name=songmap rows=50 cols=120>%s</textarea><input type=submit></form></body</html>" % json.dumps(self.sonobo.get_songmap_json(), indent=2)).encode('utf-8'))


    def do_POST(self) -> None:
        print('do_POST')
        ctype: str
        pdict_str: dict[str, str]
        ctype, pdict_str = cgi.parse_header(self.headers['content-type'])
        print(pdict_str);

        # Convert dict[str, str] to dict[str, bytes] to satisfy cgi.parse_multipart typechecking
        pdict: dict[str, bytes] = {}
        for pkey in pdict_str:
            pdict[pkey] = bytes(pdict_str[pkey], 'utf-8')

        if ctype == 'multipart/form-data':
            self.send_response(500)
            self.send_header('content-type','text/html')
            self.end_headers()
            self.wfile.write('form-multipart not supported'.encode('utf-8'))
            return
#            postvars: dict[str, list[typing.Any]] = cgi.parse_multipart(self.rfile, pdict)
#            print("songmap (multipart): %s\n" % postvars[b'songmap'])

        if ctype != 'application/x-www-form-urlencoded':
            self.send_response(500)
            self.send_header('content-type','text/html')
            self.end_headers()
            self.wfile.write(("unknown content type %s" % ctype).encode('utf-8'))
            return

        length: int = int(self.headers['content-length'])
        body: bytes = self.rfile.read(length)
        postvars: dict[str, list[str]] = urllib.parse.parse_qs(
            body.decode('utf-8'),
            keep_blank_values=True)

        print("smap: %s", postvars['songmap'][0])
        songmap_json: list[JsonSongT] = json.loads(postvars['songmap'][0])
        self.sonobo.update_code_to_song_map(songmap_json)

        shutil.copyfile('songmap.json', 'songmap-%d.json' % time.time())

        with open('songmap.tmp', 'w') as outfile:
            json.dump(songmap_json, outfile, indent=2)

        shutil.move('songmap.tmp', 'songmap.json')
        self.json_songmap = songmap_json

        self.send_response(200)
        self.send_header('content-type','text/html')
        self.end_headers()
        self.wfile.write(b'OK')
        # TODO: error handling / sanity checking

def main() -> None:
    print("discovering sonos...")
    speakers = soco.discover()

    raw_songmap_contents = open('songmap.json')
    json_songmap_contents: list[JsonSongT] = json.load(raw_songmap_contents)
    key_code_to_song_map: dict[int, SongInfo]  = songmap_json_to_map(json_songmap_contents)
    print(key_code_to_song_map)

    for speaker in speakers:
        print(" - %s" % (speaker.player_name))

    living_room_speaker = speaker_with_name(speakers, 'Living Room')

    print("Creating sonobo")
    sonobo = Sonobo(json_songmap_contents, living_room_speaker)

    print("Creating HTTP server")
    def hwrapper(*args):
        SonoboHTTPHandler(sonobo, *args)
    server = http.server.HTTPServer(('0.0.0.0', 8080), hwrapper)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    print("Starting sonobo")
    sonobo.loop()

    print("Done.")

if __name__ == "__main__":
    main()
