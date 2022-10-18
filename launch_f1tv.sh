#!/bin/bash
if pgrep MultiViewer > /dev/null
then
    xdotool search --onlyvisible --all --name 'MultiViewer for F1' windowactivate
    xdotool key ctrl+w
    xdotool search --name 'workspace/streamdeck' windowactivate
    xdotool key ctrl+Page_Down
    xdotool type 'exit'
    xdotool key Return
else
    xdotool search --name 'workspace/streamdeck' windowactivate
    xdotool key ctrl+shift+T
    xdotool type 'cd ../MultiViewer\ for\ F1-linux-x64'
    xdotool key Return 
    xdotool type './MultiViewer\ for\ F1'
    xdotool key Return 
    xdotool search --name 'MultiViewer for F1-linux' --sync windowactivate
    xdotool key ctrl+Page_Down
fi
