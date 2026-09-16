#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
./open_audio_profile.sh
./toggle_stream_audio_profile.sh
