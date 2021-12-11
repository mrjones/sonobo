import soco
from soco.plugins.sharelink import ShareLinkPlugin
import struct


EVENT_DEVICE_PATH = '/dev/input/by-id/usb-Telink_Wireless_Receiver-if01-event-kbd'

def speaker_with_name(speakers, name):
    for speaker in speakers:
        if speaker.player_name == name:
            return speaker
    raise ValueError('Could not find speaker with name "%s"' % name)

def main():
    print("discovering sonos...")
    speakers = soco.discover()

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

            KEY_Q = 16
            KEY_W = 17
            KEY_E = 18
            KEY_R = 19
            KEY_T = 20
            KEY_Y = 21
            KEY_U = 22
            KEY_I = 23
            KEY_O = 24
            KEY_P = 25

            KEY_A = 30
            KEY_S = 31
            KEY_D = 32
            KEY_F = 33
            KEY_G = 34
            KEY_H = 35
            KEY_J = 36
            KEY_K = 37
            KEY_L = 38

            KEY_Z = 44
            KEY_X = 45
            KEY_C = 46
            KEY_V = 47
            KEY_B = 48
            KEY_N = 49
            KEY_M = 50

            key_to_song_map = {
                KEY_T: 'https://open.spotify.com/track/2w7O4XCRoIJrwF1NqKL9TM?si=1a351eda12024804',
                KEY_O: 'https://open.spotify.com/track/2eDdFHgqNJltzlvlZFVDWd?si=267f73b46faa4784'
            }

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
                elif code in key_to_song_map:
                    song = key_to_song_map[code];
                    print('Song %s' % song)
                    living_room_speaker.clear_queue()
                    living_room_sharelink = ShareLinkPlugin(living_room_speaker)
                    living_room_sharelink.add_share_link_to_queue(song)
                    living_room_speaker.play()

    print("Done.")

if __name__ == "__main__":
    main()
