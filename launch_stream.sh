#!/bin/bash
if pgrep -x obs > /dev/null
then
    xdotool search --name 'Profile: hack.party' windowactivate
    xdotool key ctrl+q
    xdotool search --name 'X AIR Edit' windowactivate
    xdotool key ctrl+q
    xdotool search --name 'Downloads/X-AIR-Edit_LINUX_1.7' windowactivate
    sleep 4 
    xdotool key ctrl+shift+w
    xdotool key ctrl+shift+w
else
    xdotool search --name 'workspace/streamdeck' windowactivate
    xdotool key ctrl+shift+T
    xdotool type 'obs'
    xdotool key Return 
    xdotool search --name 'workspace/streamdeck' windowactivate
    xdotool key ctrl+shift+T
    xdotool type 'cd ~/Downloads/X-AIR-Edit_LINUX_1.7'
    xdotool key Return 
    xdotool type './X-AIR-Edit'
    xdotool key Return
fi
