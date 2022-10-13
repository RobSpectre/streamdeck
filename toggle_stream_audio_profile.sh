#!/bin/bash
if [ -f mixer_in_desktop.txt ]
then
    xdotool mousemove 2231 977 
    xdotool click 1
    xdotool key Return
    rm mixer_in_desktop.txt
else
    xdotool mousemove 2231 977 
    xdotool click 1
    xdotool key --repeat 5 Up
    xdotool key Return
    touch mixer_in_desktop.txt
fi
