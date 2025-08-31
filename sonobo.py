# TODO
# - Webserver UI for editing songmap.json
# - Logs to Webserver UI
# - try-catch / error recovery
# - Support multi-room joining

import cgi
import datetime
import http.server
import logging
import logging.handlers
import json
import os
import shutil
import socket
import struct
import sys
import threading
import time
import urllib.parse

import typing
import typing_extensions

import soco # type: ignore
import soco.plugins.sharelink # type: ignore

log = logging.getLogger("sonobo")

MAX_VOLUME = 19
FAST_REPEAT_THRESHOLD_SEC = 4.0

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

class Clock:
    def now_ts(self):
        return time.time_ns() / 1000000

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

    def __init__(self, songmap_json: list[JsonSongT], speaker, clock: Clock):
        self.songmap_json = songmap_json
        self.key_code_to_song_map = songmap_json_to_map(songmap_json)
        self.speaker = speaker
        self.clock = clock
        self.last_key = -1
        self.last_key_timestamp = 0.0 # seconds

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
        log.info("Received new code-to-song map with %d songs", (len(code_to_song_map)))
        for item in code_to_song_map.items():
            log.debug(item)
        self.mutex.acquire()
        try:
            self.songmap_json = songmap_json
            self.key_code_to_song_map = code_to_song_map
        finally:
            self.mutex.release()

    def coordinator(self):
        return self.speaker.group.coordinator

    def get_keypress(self, keyboard_dev_file: typing.BinaryIO) -> typing.Tuple[int, int, int, float]:
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
        timestamp = (_tv_sec * 1000000 + _tv_usec)/1000000

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

        return (typet, code, value, timestamp)

    def dispatch(self, typet: int, code: int, value: int, timestamp: float) -> None:
        if typet == EV_KEY and value == 1:
            # Keypress
            log.info("%d pressed", code)
            fast_repeat = False
            if self.last_key == code and self.last_key_timestamp is not None:
                delay = timestamp - self.last_key_timestamp
                log.info("Delay between repeat keypresses: %s", "{:10.4f}".format(delay))
                if delay < FAST_REPEAT_THRESHOLD_SEC:
                    fast_repeat = True

            if code == KEY_SPACE:
                if self.coordinator().get_current_transport_info()['current_transport_state'] != 'PLAYING':
                    log.info("Play")
                    self.coordinator().play()
                else:
                    log.info("Pause")
                    self.coordinator().pause()
            elif code == KEY_BACKSPACE:
                log.info("Pause")
                self.coordinator().pause()
            elif code == KEY_UP:
                current_vol = self.coordinator().volume
                if current_vol >= MAX_VOLUME:
                    log.info("Volume-up capped at %d", current_vol)
                else:
                    delta = min(2, MAX_VOLUME - current_vol)
                    log.info("Volume up (%d + %d)", current_vol, delta)
                    self.coordinator().set_relative_volume(delta)
            elif code == KEY_DOWN:
                current_vol = self.coordinator().volume
                if current_vol <= 0:
                    log.info("Volume-down capped at 0")
                else:
                    delta = min(2, current_vol)
                    log.info("Volume down (%d - %d)", current_vol, delta)
                    self.coordinator().set_relative_volume(-1 * delta)
            elif code == KEY_RIGHT:
                log.info("Next")
                self.coordinator().next()
            elif code == KEY_LEFT:
                log.info("Previous")
                self.coordinator().previous()
            elif code == KEY_F12:
                log.info("=== Dumping Sonos Playlist IDs ===")
                for playlist in self.coordinator().get_sonos_playlists():
                    log.info("title=%s item_id=%s", playlist.title, playlist.item_id)
            elif song := self.song_for_code(code):
                if fast_repeat:
                    log.info("Ignoring fast-repeat of %d", code)
                else:
                    log.info('Song %s', song)
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
                        log.info('unknown song kind: %s', song.kind)

            self.last_key = code
            self.last_key_timestamp = timestamp

    def loop(self) -> None:
        log.info('opening "%s"', EVENT_DEVICE_PATH)
        with open(EVENT_DEVICE_PATH, 'rb') as f:
            log.info('READY')
            while True:
                try:
                    self.dispatch(*self.get_keypress(f))
                except Exception as e:
                    log.exception(e)

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
    def __init__(self, sonobo: Sonobo, log_filename: str, *args):
        self.sonobo = sonobo
        self.log_filename = log_filename
        self.json_songmap: typing.Optional[list[JsonSongT]] = None
        super().__init__(*args)

    def do_GET(self) -> None:
        log.info('do_GET %s', self.path)
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type','text/html')
            self.end_headers()
            self.wfile.write(("<html><body><div><a href=/log>Log</a></div><div><form method=POST action=/updatesongmap><textarea name=songmap rows=50 cols=120>%s</textarea></div><div><input type=submit></div></form></body</html>" % json.dumps(self.sonobo.get_songmap_json(), indent=2)).encode('utf-8'))
        elif self.path.startswith('/log'):
            self._handle_log_request()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'')
        log.info('do_GET done')

    def _handle_log_request(self) -> None:
        # Parse query parameters
        url_parts = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(url_parts.query)
        
        # Configuration
        lines_per_page = 100
        
        # Get page number (default to last page)
        try:
            total_lines = sum(1 for _ in open(self.log_filename, 'r'))
        except (IOError, OSError):
            self.send_response(404)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body>Log file not found</body></html>')
            return
            
        total_pages = max(1, (total_lines + lines_per_page - 1) // lines_per_page)
        
        # Default to last page (tail of file)
        page = int(query_params.get('page', [total_pages])[0])
        page = max(1, min(page, total_pages))
        
        # Calculate line range for this page
        start_line = (page - 1) * lines_per_page
        end_line = min(start_line + lines_per_page, total_lines)
        
        # Read the specific chunk of the file
        try:
            with open(self.log_filename, 'r') as log_file:
                lines = []
                for i, line in enumerate(log_file):
                    if i >= start_line and i < end_line:
                        lines.append(line.rstrip('\n'))
                    elif i >= end_line:
                        break
                        
            log_content = '\n'.join(lines)
        except (IOError, OSError):
            log_content = "Error reading log file"
        
        # Generate HTML response
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Sonobo Log Viewer</title>
    <style>
        body {{ font-family: monospace; margin: 20px; }}
        .nav {{ margin-bottom: 20px; }}
        .nav button {{ margin: 5px; padding: 10px 15px; }}
        .log-content {{ 
            background-color: #f5f5f5; 
            border: 1px solid #ddd; 
            padding: 15px; 
            white-space: pre-wrap; 
            overflow-x: auto; 
            max-height: 70vh; 
            overflow-y: auto;
        }}
        .info {{ margin-bottom: 10px; color: #666; }}
    </style>
</head>
<body>
    <h1>Sonobo Log Viewer</h1>
    <div class="info">
        Showing lines {start_line + 1}-{end_line} of {total_lines} 
        (Page {page} of {total_pages}, {lines_per_page} lines per page)
    </div>
    <div class="nav">
        <form style="display: inline;" method="get" action="/log">
            <input type="hidden" name="page" value="1">
            <button type="submit" {'disabled' if page <= 1 else ''}>⏮️ First</button>
        </form>
        <form style="display: inline;" method="get" action="/log">
            <input type="hidden" name="page" value="{page - 1}">
            <button type="submit" {'disabled' if page <= 1 else ''}>⬅️ Previous</button>
        </form>
        <form style="display: inline;" method="get" action="/log">
            <input type="hidden" name="page" value="{page + 1}">
            <button type="submit" {'disabled' if page >= total_pages else ''}>➡️ Next</button>
        </form>
        <form style="display: inline;" method="get" action="/log">
            <input type="hidden" name="page" value="{total_pages}">
            <button type="submit" {'disabled' if page >= total_pages else ''}>⏭️ Last</button>
        </form>
        <form style="display: inline;" method="get" action="/log">
            Page: <input type="number" name="page" value="{page}" min="1" max="{total_pages}" style="width: 60px;">
            <button type="submit">Go</button>
        </form>
        <a href="/" style="margin-left: 20px;">⬅️ Back to Home</a>
    </div>
    <div class="log-content">{log_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}</div>
</body>
</html>"""
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def do_POST(self) -> None:
        log.info('do_POST %s', self.path)
        if self.path == '/updatesongmap':
            ctype: str
            pdict_str: dict[str, str]
            ctype, pdict_str = cgi.parse_header(self.headers['content-type'])

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
#            log.info("songmap (multipart): %s\n" % postvars[b'songmap'])

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

            log.debug("smap: %s", postvars['songmap'][0])
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
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'')
        log.info('do_POST done')

def get_ip_address() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect(("8.8.8.8", 80))
    address = sock.getsockname()[0]
    sock.close()
    return address

def main() -> None:
    LIVE_LOG_FILENAME = os.environ.get("LOGFILE", "sonobo.log")
    PREV_LOG_FILENAME = LIVE_LOG_FILENAME + ".prev"

    if os.path.exists(LIVE_LOG_FILENAME):
        os.rename(LIVE_LOG_FILENAME, PREV_LOG_FILENAME)

    formatter = logging.Formatter("[%(levelname).1s%(asctime)s.%(msecs)03d] %(message)s", "%Y%m%d %H:%M:%S")
    file_handler = logging.handlers.WatchedFileHandler(LIVE_LOG_FILENAME)
    file_handler.setFormatter(formatter)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    log.setLevel(os.environ.get("LOGLEVEL", "INFO"))
    log.addHandler(stdout_handler)
    log.addHandler(file_handler)

    log.info("discovering sonos...")
    speakers = soco.discover()
    for speaker in speakers:
        log.info(" - %s", speaker.player_name)

    log.info("Using 'Living Room'")
    living_room_speaker = speaker_with_name(speakers, 'Living Room')

    raw_songmap_contents = open('songmap.json')
    json_songmap_contents: list[JsonSongT] = json.load(raw_songmap_contents)
    key_code_to_song_map: dict[int, SongInfo]  = songmap_json_to_map(json_songmap_contents)
    log.info("Song map (%s) has %d songs", 'songmap.json', len(key_code_to_song_map))
    log.debug(key_code_to_song_map)

    sonobo = Sonobo(json_songmap_contents, living_room_speaker, Clock())

    HTTP_PORT = 8080
    def hwrapper(*args):
        SonoboHTTPHandler(sonobo, LIVE_LOG_FILENAME, *args)
    server = http.server.HTTPServer(('0.0.0.0', HTTP_PORT), hwrapper)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    log.info("HTTPServer running: http://%s:%d", get_ip_address(), HTTP_PORT)
    log.info("Sonobo initializing...")
    sonobo.loop()

    log.info("Exiting.")

if __name__ == "__main__":
    main()
