# TODO
# - Webserver UI for editing songmap.json
# - Logs to Webserver UI
# - try-catch / error recovery
# - Support multi-room joining

import cgi
import http.server
import json
import shutil
import soco
import soco.plugins.sharelink
import struct
import threading
import time
import urllib.parse

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
    songmap_json = None
    key_code_to_song_map: dict[str, SongInfo] = {}
    mutex = threading.Lock()
    speaker = None

    def __init__(self, songmap_json, speaker):
        self.songmap_json = songmap_json
        self.key_code_to_song_map = songmap_json_to_map(songmap_json)
        self.speaker = speaker

    def get_songmap_json(self):
        self.mutex.acquire()
        try:
            return self.songmap_json
        finally:
            self.mutex.release()

    def song_for_code(self, code):
        self.mutex.acquire()
        try:
            if code in self.key_code_to_song_map:
                return self.key_code_to_song_map[code]
            else:
                return None
        finally:
            self.mutex.release()

    def update_code_to_song_map(self, songmap_json):
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

    def loop(self):
        print('opening "%s"' % (EVENT_DEVICE_PATH))
        with open(EVENT_DEVICE_PATH, 'rb') as f:
            print('READY')
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
                    elif song := self.song_for_code(code):
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
                            self.coordinator().add_to_queue(playlist);
                            self.coordinator().play()
                        else:
                            print('unknown song kind: %s' % song.kind)


def speaker_with_name(speakers, name):
    for speaker in speakers:
        if speaker.player_name == name:
            return speaker
    raise ValueError('Could not find speaker with name "%s"' % name)

def songmap_json_to_map(json_songmap_contents) -> dict[str, SongInfo]:
    key_code_to_song_map = {}
    for song in json_songmap_contents:
        key_code_to_song_map[KEY_STRING_TO_CODE_MAP[song['key']]] = SongInfo(song['payload'], song['kind'])
    return key_code_to_song_map


class SonoboHTTPHandler(http.server.BaseHTTPRequestHandler):
    sonobo: Sonobo = None
    json_songmap = None

    def __init__(self, sonobo: Sonobo, *args):
        self.sonobo = sonobo
        http.server.BaseHTTPRequestHandler.__init__(self, *args)

    def do_GET(self):
        print('do_GET')
        self.send_response(200)
        self.send_header('Content-type','text/html')
        self.end_headers()
        self.wfile.write(("<html><body><form method=POST action=/updatesongmap><textarea name=songmap rows=50 cols=120>%s</textarea><input type=submit></form></body</html>" % json.dumps(self.sonobo.get_songmap_json(), indent=2)).encode('utf-8'))


    def do_POST(self):
        print('do_POST')
        ctype, pdict = cgi.parse_header(self.headers['content-type'])
        if ctype == 'multipart/form-data':
            postvars = cgi.parse_multipart(self.rfile, pdict)
            print("songmap: %s\n", postvars[b'songmap'])
        elif ctype == 'application/x-www-form-urlencoded':
            length = int(self.headers['content-length'])
            postvars = urllib.parse.parse_qs(
                    self.rfile.read(length),
                    keep_blank_values=1)
            print("songmap: %s\n", postvars[b'songmap'])
        else:
            self.send_response(500)
            self.send_header('content-type','text/html')
            self.end_headers()
            self.wfile.write(("unknown content type %s" % ctype).encode('utf-8'))

        print("smap: %s", postvars[b'songmap'][0])
        songmap_json = json.loads(postvars[b'songmap'][0])
        self.sonobo.update_code_to_song_map(songmap_json)
#        song_map = songmap_json_to_map(songmap_json)

        shutil.copyfile('songmap.json', 'songmap-%d.json' % time.time())

        with open('songmap.tmp', 'w') as outfile:
            json.dump(songmap_json, outfile, indent=2)

        shutil.move('songmap.tmp', 'songmap.json')
        self.json_songmap = songmap_json

        self.send_response(200)
        self.send_header('content-type','text/html')
        self.end_headers()
        self.wfile.write(b'OK')
        # TODO: backup the old file and rename it
        # TODO: error handling / sanity checking


def main():
    print("discovering sonos...")
    speakers = soco.discover()

    raw_songmap_contents = open('songmap.json')
    json_songmap_contents = json.load(raw_songmap_contents)
    key_code_to_song_map = songmap_json_to_map(json_songmap_contents)
    print(key_code_to_song_map);

    for speaker in speakers:
        print(" - %s" % (speaker.player_name))

    living_room_speaker = speaker_with_name(speakers, 'Living Room')

    print("Creating sonobo")
    sonobo = Sonobo(json_songmap_contents, living_room_speaker);

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
