# Stream Deck configuration for OpenDeck

Native OpenDeck profiles live in `opendeck/profiles/`. The sole configuration
source is `opendeck-layout.json`: 10 XL pages and one three-button
page. Retired streamdeck-ui snapshots and unused assets have been removed; their
history remains available in Git.
Icons are bundled in `opendeck/images/hackparty/` and referenced relative to the
OpenDeck configuration directory. OpenDeck blocks external image paths by default.

## Install

Install **OpenDeck Starter Pack**, then quit OpenDeck completely and stop the
old streamdeck-ui application if it is still installed. From this repository run:

```sh
python3 tools/build_opendeck.py
python3 tools/install_opendeck.py
```

The installer backs up existing profiles, removes only the previously migrated
profile filenames, and copies the current profiles **and icons**. Unrelated
profiles remain. Restart OpenDeck afterward. The XL opens page 2 and the
three-button device opens page 1, matching the source file's selected pages.

For Flatpak, use:

```sh
python3 tools/install_opendeck.py --config "$HOME/.var/app/me.amankhanna.opendeck/config/opendeck"
```

These are native configuration files, not ZIP files for the profile importer.
If installing manually, copy both `opendeck/profiles/` and `opendeck/images/`
into the OpenDeck config directory with OpenDeck stopped.

Keep this repository in place for command scripts. If it moves, regenerate and
reinstall. Icons are self-contained after installation. Suggested global settings
are brightness **86**, rotation **0**, and sleep timeout **0** minutes; preserve
other settings if applying `opendeck/settings-recommended.json` manually.

## XL page order

1. broadcast
2. soundboard
3. Background Selection — all 21 sources in OBS's Loops scene
4. Formula 1
5. Formula 1 Page 2
6. Page 6 — paging buttons only
7. Page 7 — paging buttons only
8. Page 8
9. Page 9
10. Page 10

Names are saved in each device's `page_names` mapping under `devices` in the source configuration. All
previous/next buttons follow this order. The six broadcast loop selectors have
moved to Background Selection. Their former slots now contain copies of Rap Horn,
Winner, Vibing, Crickets, Laughs, and Sad from the soundboard.

### OBS background selection

`control_obs_background.py` selects exactly one direct source in the `Loops`
scene of the `hack.party` collection. Nested scenes stay intact, including their
visualizers. Pressing a selected background again leaves it selected. Source
IDs are resolved live, so reordering OBS sources does not break buttons.

Enable the authenticated server in OBS → Tools → WebSocket Server Settings.
The helper reads the port and password from OBS's local configuration and
connects only to localhost. Credentials are not copied into this repository.
The configured source names are listed in `obs_backgrounds.json`.

```sh
.venv/bin/python control_obs_background.py --list
.venv/bin/python control_obs_background.py 'Space Highway'
```

Background buttons use live gray/off and amber/selected indicators, with red
for unavailable status. Selecting another background updates all 21 keys; pressing
the selected key keeps it selected. Manual OBS visibility changes also update
the indicators. Buttons use existing repository icons; labels may abbreviate long
OBS source names. Commands retain the exact names. The helper uses OBS's
[scene item visibility API](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md#setsceneitemenabled).

## Live broadcast indicators

PiP, Portrait, Face, Game, Video, Office, Chroma Key, Ada Cam, BRB, the four
corner layouts, and Key/Fill lights use the bundled **Hackparty Live Status**
OpenDeck plugin. Their icons are dim gray when inactive, amber when active,
and red when status is unavailable. It polls OBS and the lights about once per
second while the controls are visible, and refreshes after presses. Manual OBS
or light changes are reflected automatically.

Scene buttons select the scene even when already active. Face/Ada, Game/Video/
Office, and Chroma Key control the matching OBS sources; Chroma Key switches
between the camera versions. Video controls Loops, while Office controls Office
(the old shortcut accidentally controlled Loops for both). Key and Fill toggle
the actual light state. Settings live in each source button's `live_control`
field. The plugin launcher uses this repository's `.venv` and scripts, and waits for
them to become available if OpenDeck starts before the Storage drive mounts.

Run the complete verification suite, including plugin tests, with
`.venv/bin/python -m unittest discover -s tests -v`.

### Soundboard effect indicators

The first two rows of soundboard action buttons plus Noooo use live effect
indicators, as do the broadcast copies of Winner, Vibing, Crickets, Laughs, and
Sad. Paging buttons and one-shot Rap Horn keep their existing behavior.

Jump Around and the soundboard bottom row are cleared.

Effect targets were taken from the existing OBS shortcut bindings. Paired sounds
and visuals toggle together. Amber means at least one member of the effect is
visible; pressing it then disables all members. Gray means all are off; pressing
it enables them together. Copies share the same effect identity and follow OBS
visibility changes. Red means a target or OBS connection is unavailable.

### Audio Mode and Mute

These two buttons use **local button state only**, independent of OBS and mixer
polling. The initial mode is Desktop. Entering Broadcast resets the tracked mic
state to hot; Mute toggles it. Both keys glow red only while Broadcast is selected
and the mic is unmuted. Desktop is always gray, and muting in Broadcast makes
both keys gray. The labels distinguish Desktop, Broadcast/hot, and Broadcast/muted.

The existing audio/mute scripts still perform the actions. Local state is saved
only after the command succeeds, in the ignored `.audio-control-state.json` file,
and survives OpenDeck restarts. These indicators assume audio changes happen
only through these two buttons, as configured; they do not verify mixer state.

## Editing key labels in OpenDeck

Edit the title in any state of a live-status key. The plugin immediately copies
that title to its other states and saves it in `opendeck-labels.json`. It also
restores the saved title when the key appears again. Keys have stable `label_id`
values in the source configuration, so overrides follow them when moved.

The generator imports app-edited labels by default from native OpenDeck config;
use `--config PATH` for another installation (including Flatpak). The installer
also captures the latest edits before replacing profiles, so edits made after
generation survive installation. Single-state keys and intentional per-state
labels such as Audio Mode, Mic and Blur are preserved during generation/install;
the intentional labels are not collapsed into one shared title.

`--no-import-labels` skips reading installed profiles; it still applies saved
overrides. To reset a label, edit it in OpenDeck to the desired original text.
Backups remain available before installation.
Only title text is preserved by this feature; icon/font/position edits are not
merged automatically. Future general profile installations still use the repo
layout as their source.

## Runtime dependencies

OpenDeck replaces the old Python streamdeck-ui application. Python packages in
`requirements.txt` support the live-status plugin, OBS, light, and MultiViewer helpers:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Formula 1 runtime state (`state.json`) and the mixer mode marker
(`mixer_in_desktop.txt`) are ignored by Git. Formula 1 uses `state_default.json`
until runtime state exists; launching Formula 1 resets it to those defaults.

The generated command actions prepend `.venv/bin` to PATH when that environment
exists. Otherwise they use the PATH inherited by OpenDeck. Existing commands
use `python`, `mvf1-cli`, `xdotool`, and SoX `play`; those executables and the
controlled apps (OBS, X AIR Edit, browser, MultiViewer) must be available.
The existing desktop shortcuts use X11/xdotool and still require an X11 session.
Audio files outside this repository and application window titles remain
machine-specific, as in the original configuration.

## Profile behavior and limits

- Commands use Starter Pack **Run Command**, explicitly changing into this
  repository so relative scripts, light settings, and driver state files work.
- Page numbers are converted from one-based targets to named OpenDeck
  profiles. Button positions are unchanged; unused positions stay empty.
- Keyboard shortcuts and typed text use xdotool. Commands plus page switching
  use OpenDeck Multi Action. Long-running commands can overlap the page switch;
  the command does not wait for those programs to exit before navigation.
- The Blur key is dim gray with “Blur OFF” when off and has an amber glow
  with “Blur ON” when on. Pressing it alternates the appearances and commands.
  It uses authenticated OBS WebSocket commands. Blur adds/enables
  the Composite Blur filter on the current program scene (the full composed
  picture). Stop Blur disables every filter created by this helper, including
  on scenes used earlier. A newly selected scene does not inherit another
  scene's blur. The button has explicit on/off states and is not synchronized
  with manual filter changes in OBS. Other blur filters are left alone.
- Existing icon files are copied byte-for-byte, including animated assets.
  Labels default to 11-point text. Titles and nonempty appearance settings are mapped; font rendering can differ.
- OpenDeck's brightness, rotation, and sleep settings are global. Suggested
  settings favor the XL: brightness 86, rotation 0, and sleep disabled.
- Future unsupported brightness actions, horizontal text alignment, or
  nonsequential state transitions cause conversion to fail rather than disappear.

## Regenerate and verify

```sh
python3 tools/build_opendeck.py
.venv/bin/python -m unittest discover -s tests -v
```

Use `--output PATH` to stage files elsewhere or `--repo-root PATH` to set the
runtime location of scripts and images. Verification checks all page links,
positions, child contexts, shell syntax, the blur toggle, and safe shell quoting
with a fake input executable. Icon bytes and config-relative paths are also checked. Builds remove unused
bundled icons from `opendeck/images/hackparty/`. No tests send keystrokes or operate real devices.
Hardware operation and visual appearance still need checking in OpenDeck.

Schema and behavior were checked against OpenDeck commit
`7cc07942ef4a0d4d04d3011fac3f82626a211cfb` using its
[AGENTS.md](https://github.com/nekename/OpenDeck/blob/7cc07942ef4a0d4d04d3011fac3f82626a211cfb/AGENTS.md),
[disk profile schema](https://github.com/nekename/OpenDeck/blob/7cc07942ef4a0d4d04d3011fac3f82626a211cfb/src-tauri/src/store/simplified_profile.rs),
and Starter Pack action implementations. Use a version compatible with that
schema; older OpenDeck versions may differ.
