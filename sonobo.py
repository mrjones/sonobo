import json
import soco
from soco.plugins.sharelink import ShareLinkPlugin
import struct


EVENT_DEVICE_PATH = '/dev/input/by-id/usb-Telink_Wireless_Receiver-if01-event-kbd'

KEY_STRING_TO_CODE_MAP = {
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


def speaker_with_name(speakers, name):
    for speaker in speakers:
        if speaker.player_name == name:
            return speaker
    raise ValueError('Could not find speaker with name "%s"' % name)

def read_key_code_to_song_map():
    songmap_contents = open('songmap.json')

    key_strings_and_songs = json.load(songmap_contents)
    key_code_to_song_map = {}
    for song in key_strings_and_songs:
        key_code_to_song_map[KEY_STRING_TO_CODE_MAP[song['key']]] = song['url']

    return key_code_to_song_map

def main():
    print("discovering sonos...")
    speakers = soco.discover()

    key_code_to_song_map = read_key_code_to_song_map();
    print(key_code_to_song_map);

    for speaker in speakers:
        print(" - %s" % (speaker.player_name))

    living_room_speaker = speaker_with_name(speakers, 'Living Room')

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
            KEY_SPACE = 57
            KEY_BACKSPACE = 14

            if typet == EV_KEY and value == 1:
                # Keypress
                print("%d pressed" % (code))
                if code == KEY_SPACE:
                    if living_room_speaker.get_current_transport_info()['current_transport_state'] != 'PLAYING':
                        print("Play")
                        living_room_speaker.play()
                    else:
                        print("Pause")
                        living_room_speaker.pause()
                if code == KEY_BACKSPACE:
                    print("Pause")
                    living_room_speaker.pause()
                if code == KEY_UP:
                    current_vol = living_room_speaker.volume
                    print("Volume up (@%d)" % current_vol)
                    if living_room_speaker.volume > 15:
                        print("Volume capped")
                    else:
                        living_room_speaker.set_relative_volume(2)
                if code == KEY_DOWN:
                    print("Volume down")
                    living_room_speaker.set_relative_volume(-2)
                elif code in key_code_to_song_map:
                    song = key_code_to_song_map[code];
                    print('Song %s' % song)
#                    living_room_speaker.clear_queue()
#                    living_room_sharelink = ShareLinkPlugin(living_room_speaker)
#                    living_room_sharelink.add_share_link_to_queue(song)
#                    living_room_speaker.play()

    print("Done.")

if __name__ == "__main__":
    main()
