#!/bin/bash
xdotool mousemove --sync $2 $3 
xdotool click 3 
for i in $(seq 11)
do
    xdotool key Down
done
xdotool key Return
for i in $(seq $1)
do
    xdotool key Down
done
xdotool key Return
