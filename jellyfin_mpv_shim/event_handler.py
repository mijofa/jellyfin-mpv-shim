import importlib.resources
import logging
import os

# On Linux the pypi version of this puts annoying double-quotes in the notification.
# That has been fixed upstream though and simply not made it to pypi, can be installed with:
#     pip3 install git+https://github.com/YuriyLisovskiy/pynotifier
import pynotifier
import pynput.keyboard

from .utils import plex_color_to_mpv
from .conf import settings
from .media import Media
from .player import playerManager
from .timeline import timelineManager

log = logging.getLogger("event_handler")
bindings = {}

NAVIGATION_DICT = {
    "Back": "back",
    "Select": "ok",
    "MoveUp": "up",
    "MoveDown": "down",
    "MoveRight": "right",
    "MoveLeft": "left",
    "GoHome": "home",
}

keyboard = pynput.keyboard.Controller()

jf_cmd_to_kbrd_key = {
    'Back': pynput.keyboard.Key.esc,
    'Select': pynput.keyboard.Key.enter,
    'MoveUp': pynput.keyboard.Key.up,
    'MoveDown': pynput.keyboard.Key.down,
    'MoveRight': pynput.keyboard.Key.right,
    'MoveLeft': pynput.keyboard.Key.left,
    'GoHome': pynput.keyboard.KeyCode(269025048),  # XF86HomePage
    'ToggleContextMenu': pynput.keyboard.Key.menu,  # FIXME
    'GoToSearch': pynput.keyboard.KeyCode(269025051),  # XF86Search
}

def bind(event_name):
    def decorator(func):
        bindings[event_name] = func
        return func
    return decorator

class EventHandler(object):
    mirror = None

    def handle_event(self, client, event_name, arguments):
        if event_name in bindings:
            log.debug("Handled Event {0}: {1}".format(event_name, arguments))
            bindings[event_name](self, client, event_name, arguments)
        else:
            log.debug("Unhandled Event {0}: {1}".format(event_name, arguments))

    @bind("Play")
    def play_media(self, client, event_name, arguments):
        play_command = arguments.get('PlayCommand')
        if not playerManager._video:
            play_command = "PlayNow"

        if play_command == "PlayNow":
            media = Media(client, arguments.get("ItemIds"), seq=0, user_id=arguments.get("ControllingUserId"),
                        aid=arguments.get("AudioStreamIndex"), sid=arguments.get("SubtitleStreamIndex"), srcid=arguments.get("MediaSourceId"))

            log.debug("EventHandler::playMedia %s" % media)
            offset = arguments.get('StartPositionTicks')
            if offset is not None:
                offset /= 10000000

            video = media.video
            if video:
                if settings.pre_media_cmd:
                    os.system(settings.pre_media_cmd)
                playerManager.play(video, offset)
                timelineManager.SendTimeline()
        elif play_command == "PlayLast":
            playerManager._video.parent.insert_items(arguments.get("ItemIds"), append=True)
            playerManager.upd_player_hide()
        elif play_command == "PlayNext":
            playerManager._video.parent.insert_items(arguments.get("ItemIds"), append=False)
            playerManager.upd_player_hide()

    @bind("GeneralCommand")
    def general_command(self, client, event_name, arguments):
        command = arguments.get("Name")
        if command == "SetVolume":
            # FIXME: Set the system volume when movie isn't running
            # There is currently a bug that causes this to be spammed, so we
            # only update it if the value actually changed.
            if playerManager.get_volume(True) != int(arguments["Arguments"]["Volume"]):
                playerManager.set_volume(int(arguments["Arguments"]["Volume"]))
        elif command == "SetAudioStreamIndex":
            playerManager.set_streams(int(arguments["Arguments"]["Index"]), None)
        elif command == "SetSubtitleStreamIndex":
            playerManager.set_streams(None, int(arguments["Arguments"]["Index"]))
        elif command == "DisplayContent":
            # If you have an idle command set, this will delay it.
            timelineManager.delay_idle()
            if self.mirror:
                self.mirror.DisplayContent(client, arguments)
        elif command == "GoToSettings":
            # FIXME: Use ToggleContextMenu instead?
            playerManager.menu.show_menu()
        elif command == "DisplayMessage":
            # FIXME: This looks super ugly on Debian, I think it's using __repr__ instead of __str__ or something like that.
            #        Either patch pynotifier upstream, or replace it with something else.
            #        Also the text is very small, but that's likely a config thing in the notification daemon
            with importlib.resources.path(__package__, 'systray.png') as icon_file:
                pynotifier.Notification(
                    title=arguments['Arguments'].get('Header', ''),
                    description=arguments['Arguments'].get('Text', ''),
                    icon_path=icon_file,
                ).send()
        elif command in ("Back", "Select", "MoveUp", "MoveDown", "MoveLeft", "MoveRight", "GoHome", "ToggleContextMenu", "GoToSearch"):
            if playerManager.menu.is_menu_shown and command in NAVIGATION_DICT:
                # FIXME: Consider just letting the keyboard emulation control the mpv menu instead of doing so directly.
                #        Seems a bit cleaner to do so directly, but if doing both functions "more code is more bad"
                playerManager.menu.menu_action(NAVIGATION_DICT[command])
            else:
                k = jf_cmd_to_kbrd_key[command]
                # Pynput has no momentary press function, and I'm nervous about an exception causing the button to not be released.
                # This will release the key even if there's an exception, but continue to raise an exception due to the lack of 'except'.
                try:
                    keyboard.press(k)
                finally:
                    keyboard.release(k)
        elif command == "SendString":
            keyboard.type(arguments['Arguments'].get('String', ''))
            # FIXME: Is it worth pressing Enter after typing?
        elif command in ("Mute", "Unmute"):
            playerManager.set_mute(command == "Mute")
        elif command == "TakeScreenshot":
            playerManager.screenshot()
        elif command == "ToggleFullscreen" or command is None:
            # Currently when you hit the fullscreen button, no command is specified...
            playerManager.toggle_fullscreen()

    @bind("Playstate")
    def play_state(self, client, event_name, arguments):
        command = arguments.get("Command")
        if command == "PlayPause":
            playerManager.toggle_pause()
        elif command == "PreviousTrack":
            playerManager.play_prev()
        elif command == "NextTrack":
            playerManager.play_next()
        elif command == "Stop":
            playerManager.stop()
        elif command == "Seek":
            playerManager.seek(arguments.get("SeekPositionTicks") / 10000000)

    @bind("PlayPause")
    def pausePlay(self, client, event_name, arguments):
        playerManager.toggle_pause()
        timelineManager.SendTimeline()

eventHandler = EventHandler()
