#!/bin/sh
# OpenDeck may autostart before the Storage drive is mounted.
runtime=/media/rspectre/Storage/workspace/streamdeck/.venv/bin/python
plugin_script=/media/rspectre/Storage/workspace/streamdeck/tools/opendeck_status_plugin.py
while [ ! -x "$runtime" ] || [ ! -r "$plugin_script" ]; do
    sleep 2
done
exec "$runtime" "$plugin_script" "$@"
