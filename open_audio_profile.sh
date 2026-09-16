#!/bin/bash
set -euo pipefail
mixer_windows=$(xdotool search --onlyvisible --class '^X-AIR-Edit$') || {
    echo 'Cannot change audio mode: X AIR Edit is not open.' >&2
    exit 1
}
mixer_window=${mixer_windows%%$'\n'*}
xdotool windowactivate "$mixer_window"
for attempt in {1..20}; do
    [[ "$(xdotool getactivewindow)" == "$mixer_window" ]] && break
    sleep 0.05
done
if [[ "$(xdotool getactivewindow)" != "$mixer_window" ]]; then
    echo 'Cannot change audio mode: X AIR Edit did not gain focus.' >&2
    exit 1
fi
sleep 1
xdotool key --clearmodifiers ctrl+l
xdotool key Return
sleep 2 
xdotool mousemove 1680 815
xdotool click 1
xdotool type '/media/rspectre/Storage/Audio Production/X Air Scenes/'
xdotool key Return
