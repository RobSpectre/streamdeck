#!/bin/bash
if pgrep MultiViewer > /dev/null
then
    mvf1-cli players close
    xdotool search --onlyvisible --all --name 'MultiViewer for F1' windowactivate
    xdotool key ctrl+w
    xdotool search --name 'workspace/streamdeck' windowactivate
    xdotool key ctrl+Page_Down
    xdotool type 'exit'
    xdotool key Return
else
    xdotool search --name 'workspace/streamdeck' windowactivate
    xdotool key ctrl+shift+T
    xdotool type 'multiviewer-for-f1'
    xdotool key Return 
    cp state_default.json state.json
    xdotool search --name 'MultiViewer for F1-linux' --sync windowactivate
    xdotool key ctrl+Page_Down
fi
