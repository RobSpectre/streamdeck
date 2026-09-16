#!/bin/bash
set -euo pipefail

# Never send mixer shortcuts to whichever application happens to have focus.
mixer_windows=$(xdotool search --onlyvisible --class '^X-AIR-Edit$') || {
    echo 'Cannot mute microphones: X AIR Edit is not open.' >&2
    exit 1
}
mixer_window=${mixer_windows%%$'\n'*}
# Match the mixer application, not the GNOME decoration with the same title.
xdotool windowactivate "$mixer_window"
for attempt in {1..20}; do
    [[ "$(xdotool getactivewindow)" == "$mixer_window" ]] && break
    sleep 0.05
done
# X AIR Edit ignores XSendEvent keys sent with --window. Use XTEST keyboard
# events only after confirming that the mixer owns the active window.
for key in Home shift+m Right shift+m; do
    active_window=$(xdotool getactivewindow)
    if [[ "$active_window" != "$mixer_window" ]]; then
        echo 'Cannot mute microphones: X AIR Edit lost focus.' >&2
        exit 1
    fi
    xdotool key --clearmodifiers --delay 100 "$key"
done
