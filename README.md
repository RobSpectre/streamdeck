# Stream Deck configuration for OpenDeck

This repository runs a Linux Stream Deck XL and Stream Deck Pedal through
OpenDeck: broadcast/audio controls, a soundboard, Formula 1 helpers, and a
three-agent coding dashboard. It is a working configuration for one workstation,
not a portable installer for arbitrary desktops.

`opendeck-layout.json` is the layout source of truth. `opendeck-labels.json`
contains saved title overrides. `opendeck/` is the generated install bundle;
edit source files and regenerate rather than editing that bundle by hand.
Implementation and maintenance notes are in [AGENTS.md](AGENTS.md).

## Before running

- Use the logged-in desktop user on **Linux/X11**. Window focus and keyboard
  shortcuts depend on `xdotool`/`xprop`; Wayland is not a supported equivalent.
- Install OpenDeck and its **OpenDeck Starter Pack** plugin. Stop any old
  streamdeck-ui process so it does not compete for the hardware. Device access
  must already work in OpenDeck; this repository does not install USB rules.
- Mount `/media/rspectre/Storage` and keep this checkout at its configured path,
  `/media/rspectre/Storage/workspace/streamdeck`. Several scripts, the Hermes
  plugin, and the sound service contain explicit workstation paths.
- Install Python 3 with venv support, `xdotool`, `xprop`, `gdbus`, `xdg-open`,
  `zenity`, SoX `play`, PulseAudio-compatible `paplay`, and DejaVu Sans fonts.
  The CLI installer additionally imports **PyYAML using system Python**;
  `requirements.txt` currently does not include it. On Debian/Ubuntu the relevant
  system packages include `python3-venv`, `python3-yaml`, `x11-utils`,
  `libglib2.0-bin`, `xdg-utils`, `sox`, `pulseaudio-utils`, and `fonts-dejavu-core`.
- Create the repository `.venv` and install `requirements.txt` before starting
  live controls. The live plugin specifically requires `.venv/bin/python`.
- For broadcast controls: run OBS with authenticated localhost WebSocket enabled
  and the `hack.party` collection selected. Set reachable light addresses in
  `lights.json`; run X AIR Edit for mixer actions. Formula 1 requires MultiViewer
  and its local control API. External sound/media files must exist at the paths
  in the layout/scripts.
- For coding controls: sign into Codex desktop, initialize Claude Code CLI and
  Hermes CLI, and install the hooks below. The CLI installer expects both
  `~/.claude/settings.json` and `~/.hermes/config.yaml` to already exist. Agent
  web apps and Claude/Hermes desktop apps are outside this integration.

Do not run these helpers with sudo: their home-directory data, desktop session
bus, focus, and audio access belong to the desktop user. Different hardware
serials require updating the layout's device mappings before generation.

## Coding dashboard: Vibecoding (XL page 3)

Columns are numbered left to right; rows top to bottom.

| Row | Agent/color | Columns 2–7 |
| --- | --- | --- |
| 1 | Codex / white `#ffffff` | Turn state, tokens/sec, context left, session tokens, 30-day tokens, quota left |
| 2 | Claude Code CLI / orange `#d97757` | Same metrics |
| 3 | Hermes Agent CLI / blue `#0000f2` | Same metrics |

Top corners navigate to soundboard and Background Selection. Audio Mode is row 3, column 1. Bottom row
columns 1–5 are **Deny, Approve, Auto Session, Allow Tool, Codex Dictation**.
Bottom-row columns 6–8 toggle the Codex, Claude, and Hermes OBS overlays,
matching the copies on broadcast page 1.
The pedal's **Codex Pedal** profile maps left to Deny, right to Approve, and
leaves the middle pedal unassigned.

Turn keys show ACTIVE, IDLE, WAITING, or OFFLINE, with the model name in capitals
on at most two lines. Hermes can show OPEN when its process is detected but no
plugin telemetry is linked. WAITING is red. Context/quota keys become yellow at
**20% or less**, red at **10% or less**, using the displayed rounded percentage.
All red telemetry keys pulse their border over two seconds; text stays steady.
Red waiting means a detected request needs attention, not necessarily an error.
An ordinary question written only in chat text is not a structured input request.

Press Turn State, Context Left, or Session Tokens to focus the existing agent.
Tokens/sec opens its account activity page; 30-Day Tokens opens billing; Quota
Left is display-only. Destinations are editable in `agent-navigation.json`.
Codex/Claude links use subscription account pages; Hermes uses Nebius Token
Factory usage/payments. These links do not supply the displayed token counts.
GNOME Terminal focus selects the exact inherited tab UUID; other terminals need
an inherited WINDOWID. A missing focus target raises a key alert.

### What the numbers mean

| Metric | Codex | Claude Code CLI | Hermes Agent CLI |
| --- | --- | --- | --- |
| Activity/model | Followed local desktop tasks over internal IPC | CLI lifecycle hooks; model from statusline/transcript | CLI hooks plus native UI busy flag/model, sampled every second |
| Tokens/sec | Output / elapsed turn time, including tool and input waits; last turn retained while idle | Observed output delta / elapsed time since first sample of the turn, including waits | Native CLI rolling API output sum / matching API latency sum, rounded to integer |
| Context left | Latest request tokens / reported model window | Statusline remaining percentage | Latest request usage / Hermes-resolved model window; pre-response usage is estimated |
| Session tokens | Selected task cumulative usage | Selected local session transcript usage | Selected session usage ledger, including auxiliary tasks |
| 30-day tokens | Available local rollouts indexed by Codex | Available local JSONL transcripts | Local SQLite per-model/task usage ledger plus legacy sessions |
| Quota left | Most restrictive unexpired core quota window | Most restrictive fresh statusline rate-limit window, when supplied | `N/A`; no provider allowance feed is implemented |

The selected session favors active then recently updated sessions; the state can
reflect **any** active/waiting session for that agent. The state and model need
not identify the same session if several are open. Context capacity, cumulative
usage, and account quota measure different things.

Totals count input (including cached input) and output once; reasoning is not
added again to output. The 30-day period is rolling, not a calendar billing month.
It excludes unavailable/deleted history and other machines, so it cannot replace
provider billing. Hermes uses `session_model_usage`, not an account history
endpoint. A Hermes `≥` total is a lower bound: an aggregate ledger row crossing
the cutoff cannot be split into exact daily usage and is excluded from the sum.

Collectors run only while their agent is open and its telemetry keys are visible.
A shared presence check runs every 5 seconds; reopening an agent or showing its
keys wakes its collectors. Closing an agent clears live metrics and labels retained
historical totals `CACHED · LOCAL`. A fresh plugin process has no cached totals
until its first collection. Cached 30-day totals do not age until collection resumes.
Already-running reads may finish before sleeping; transcript offsets remain in memory.
Approval routing stays available independently of telemetry visibility.
Codex presence requires a listening desktop IPC socket; CLI presence requires an
interactive Claude or Hermes launcher. Codex quota helpers also sleep when closed
or hidden. The standalone pedal retains its short on-demand connection behavior.

While enabled, Codex history refreshes every 2 seconds, Claude/Hermes history every 5 seconds.
Visible displays poll state about once a second. Codex quota is queried every
60 seconds; quota older than 180 seconds or past its reset deadline is hidden.
Claude quota also expires after 180 seconds. Missing data is `—`; CLI quota is
`N/A` when unavailable. Hermes speed remains blank until native API samples exist.
Its API-average speed is intentionally not comparable to the other turn averages.

### Responding to requests

Keys stay dim until a detected request is pending. No approval mode is enabled by
installation. Idle presses do nothing.

- **Codex Approve/Deny:** Enter/Escape only with a pending request and the Codex
  desktop window focused. Keep the intended prompt visible; choices and free text
  retain their normal keyboard semantics. This does not select an answer for you.
- **Claude/Hermes permission prompts:** a labeled Zenity dialog shows the command
  or tool input. Approve/Deny targets only the focused dialog with the matching
  process and unique request title. Failure to show the dialog falls back to
  native approval; timeout denies. Normal agent permission policy still decides
  which operations require approval.
- **Hermes native clarification questions:** Approve confirms the highlighted
  choice or submits text already typed; Deny cancels the question and returns
  Hermes' native “use your best judgement” cancellation result. It is **not a
  stop-agent button**. Routing requires exactly one pending CLI request, no Codex
  window focused, and (for XL) no pending Codex input indicator. It dispatches to
  the request's UI loop, without global terminal keystrokes. A changed question,
  selection, or draft invalidates the queued response. Other Claude questions
  retain the native interface; they are not covered by the permission hook.
- **Auto Session:** for a supported permission request, enables subsequent
  automatic tool approvals within that selected task/process/session. Amber
  means enabled; press again to disable. Codex covers command/file approvals and
  clears on disconnect/unfollow. CLI grants are bound to the process/session and
  survive an OpenDeck restart while that owner remains alive.
- **Allow Tool:** Codex uses conversation-scoped approval; Hermes uses its native
  session rule; Claude remembers only the exact tool name **and input** in that
  session. Neither extended action answers clarification questions.
- **Codex Dictation:** sends Ctrl+Shift+D only when Codex is focused. Codex handles
  recording/transcription; this does not submit the dictated text.

All integrations use local, partly internal interfaces. Codex or agent upgrades
can require adapter changes; they are not guaranteed public APIs.

## Install

Install **OpenDeck Starter Pack**, then quit OpenDeck completely and stop the
old streamdeck-ui application if it is still installed. From this repository run:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
python3 tools/build_opendeck.py
python3 tools/install_opendeck.py
```

The installer backs up existing profiles, removes only the previously migrated
profile filenames, and copies the current profiles **and icons**. Unrelated
profiles remain. Restart OpenDeck afterward. The XL opens broadcast (page 1) and the
three-button device opens page 1, matching the source file's selected pages.

For Flatpak, use:

```sh
python3 tools/install_opendeck.py --config "$HOME/.var/app/me.amankhanna.opendeck/config/opendeck"
```

These are native configuration files, not ZIP files for the profile importer.
If installing manually, copy both `opendeck/profiles/` and `opendeck/images/`
into the OpenDeck config directory with OpenDeck stopped.

Keep this repository in place for command scripts. If it moves, update hardcoded
paths in the Hermes plugin and sound service as well as regenerating/reinstalling
profiles and CLI hooks. `--repo-root` alone does not relocate those integrations. Icons are self-contained after installation. Suggested global settings
are brightness **86**, rotation **0**, and sleep timeout **0** minutes; preserve
other settings if applying `opendeck/settings-recommended.json` manually.

## XL page order

1. broadcast
2. soundboard
3. Vibecoding — coding telemetry, response controls, overlays and media
4. Background Selection — all 21 sources in OBS's Loops scene
5. Formula 1
6. Formula 1 Page 2
7. Page 7 — paging buttons only
8. Page 8
9. Page 9
10. Page 10

Broadcast retains its original button positions. Previous/next arrows follow
the reordered sequence.

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

## Install or update the agent integrations

After initializing both CLI agents and installing system PyYAML/Zenity:

```sh
python3 tools/install_cli_agent_integration.py
```

This adds Claude lifecycle/permission hooks and a statusline wrapper, copies the
Hermes plugin to `~/.hermes/plugins/opendeck-cli`, enables it, and configures its
approval transport with builtin fallback. Claude's original statusline command
is preserved and still invoked. Backups are written beside each config; prior
Hermes plugin copies and the original Claude statusline are kept under
`~/.cache/opendeck-agents/`. The YAML rewrite can change formatting/comments.
This installer changes **both** agents; it has no single-agent flag.

Start new CLI sessions after installation. Hermes loads plugin code at process
startup: restart Hermes after plugin updates, when its current work permits.
Updating files cannot upgrade an already running Hermes process. Claude bridge
code is read on each hook invocation, but changed hook configuration should be
loaded in a new session. Restart OpenDeck after changing its Python plugin code.
Do not kill agents mid-turn to refresh telemetry.

### Codex completion sounds

This separate user service works even when OpenDeck is closed. It watches new
terminal turns in `~/.codex/thread_history_1.sqlite` once per second:

| Turn result | Sound in `/media/rspectre/Storage/Video/Sound Effects` |
| --- | --- |
| `completed` | `mk64_item_drop.wav` |
| `failed` | `icq.wav` |
| `interrupted` | Silent |

Existing terminal turns are skipped on service startup; missed events during
service downtime are not replayed. It watches all recorded local Codex turns,
not only the focused task. Playback uses `paplay` and the desktop user's audio
server. After checking the absolute paths in the service/script:

```sh
mkdir -p "$HOME/.config/systemd/user"
cp tools/codex-turn-sounds.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now codex-turn-sounds.service
systemctl --user status codex-turn-sounds.service
journalctl --user -u codex-turn-sounds.service -n 50 --no-pager
```

To stop sounds: `systemctl --user disable --now codex-turn-sounds.service`.
Restart that service after modifying its script; run daemon-reload as well after
editing the installed unit. Sound errors are logged; a failed playback is not
retried for that turn.

## Daily operation and troubleshooting

Launch OpenDeck after the desktop and storage are available. Its generated live
plugin launcher waits for the checkout and venv, but does not mount the drive or
install dependencies. Launch only the controlled apps you need. The integration
does not start coding turns just to populate metrics.

| Symptom | Check/action |
| --- | --- |
| Profiles/icons missing | Starter Pack installed, correct native/Flatpak config path, profiles **and** images copied with OpenDeck fully stopped |
| All live keys stale | Drive mounted, `.venv/bin/python` exists, requirements installed; restart OpenDeck after code updates |
| Codex OFFLINE/no prompt light | Codex desktop running and local task followed; internal socket/protocol may have changed after upgrade |
| Hermes OPEN or “RESTART HERMES” | New plugin not loaded; restart Hermes when safe. OPEN alone means a process was found, not a live turn |
| Hermes ACTIVE while idle or missing question | Check current plugin is installed and running; native `_agent_running` and `_clarify_state` adapters must match the installed Hermes version |
| Hermes no speed | Make a normal API request; a fresh process has no native samples. Confirm the current process was restarted after the throughput update |
| Token totals differ from billing | Local-only data, rolling period, cache accounting, auxiliary tasks, and Hermes `≥` cutoff; the billing link is separate from the data source |
| Quota disappears | Account feed missing, older than 3 minutes, or reset deadline passed. Hermes `N/A` is expected |
| Response press does nothing | Focus correct Codex/Zenity prompt; resolve multiple pending CLI prompts; native Hermes questions must meet the routing conditions above |
| OBS keys red | Correct scene collection, WebSocket authentication, exact configured source names; `control_obs_background.py --list` diagnoses source access |
| Audio indicator disagrees with mixer | Indicator tracks successful button actions, not actual mixer state; reconcile manually in X AIR Edit before resuming button control |
| Focus/mixer shortcut fails | X11 session, correct window class, desktop environment variables; mixer scene loading also depends on screen coordinates and scene-file ordering |
| Sounds missing | User service status/journal, source WAV files, `paplay`, mounted drive, and desktop PulseAudio/PipeWire socket |

Useful read-only diagnostics from the checkout:

```sh
printf '%s\n' "$XDG_SESSION_TYPE"
pgrep -af 'opendeck|opendeck_status_plugin.py'
.venv/bin/python -c 'import PIL, requests, websocket, obsws_python'
python3 -c 'import yaml'
.venv/bin/python control_obs_background.py --list
systemctl --user status codex-turn-sounds.service
```

For plugin startup errors, quit OpenDeck and run `/usr/bin/opendeck` from a desktop
terminal to see its output. Do not invoke `opendeck_status_plugin.py` directly:
it expects OpenDeck's registration arguments and WebSocket. Agent cache JSON under
`~/.cache/opendeck-agents/` helps diagnose PID, session, timestamps and telemetry;
do not publish private session data or approval details in bug reports.

### Backup, rollback, and portability

The profile installer backs up existing profiles to a timestamped sibling of the
OpenDeck config directory. To roll back, stop OpenDeck and restore the relevant
profiles; those backups do **not** contain a full previous plugin/image bundle.
Regenerate/install from the desired Git revision if the plugin or assets also
need reverting. The installer preserves unrelated profiles and deletes only
known retired migration filenames.

To remove CLI integration, remove only this bridge's hook entries from Claude's
settings and restore its previous statusline from the saved JSON. In Hermes,
disable `opendeck-cli` and restore the prior approval transport (usually builtin),
then start a new session. Alternatively restore the timestamped configuration
backups, taking care to preserve unrelated changes made since installation.
Do not delete the entire Claude/Hermes configuration directories.

Runtime state is intentionally not source configuration: `.audio-control-state.json`,
`mixer_in_desktop.txt`, Formula 1 `state.json`, lock files, agent caches, and
application histories stay local. Back up the layout, labels, external media,
OBS collection and mixer scenes separately. Moving machines also requires
reviewing serial numbers, light IPs, window names/coordinates, audio-scene paths,
Codex executable/database paths and Hermes paths; regenerating profiles alone
is not a complete migration.

### Spotify-first playback on Vibecoding

Row 2, column 8 is **Play** (play/pause toggle); row 3, column 8 is **Next**
(next song). Both prefer the **Spotify desktop app** when its MPRIS interface is open, even
when paused. They send PlayPause/Next directly to that running Spotify process.
When Spotify is closed, they operate the existing Suno tab in Chrome/Chromium
through Linux AT-SPI accessibility. Spotify Web Player is not detected as the
desktop app. If Spotify is open but cannot perform the action, the key alerts
instead of unexpectedly controlling Suno. The helper selects the tab if necessary, verifies
an HTTPS `suno.com`/`www.suno.com` document, and invokes the exact **Playbar**
control. It does not send global media keys or click generic carousel Next buttons.
Select a song in Suno first; these controls do not choose music or create a queue.

System Python needs PyGObject and AT-SPI introspection (`python3-gi` and
`gir1.2-atspi-2.0` on Debian/Ubuntu), with desktop accessibility available. No
browser extension, debugging port, or persistent accessibility-setting change is
required. A missing/ambiguous Suno tab, changed page, or unavailable control raises
an OpenDeck alert. Keep one Suno tab open; tab discovery currently depends on Suno
appearing in its title. The icons are action buttons, not playback-state monitors.

To verify targeting without playing/skipping (this can select the Suno tab):

```sh
python3 tools/suno_media.py play --check
python3 tools/suno_media.py next --check
```

### Formula 1 battles (+ XL)

The dynamic keys follow the session being watched: **Race/Sprint** shows battles
and the BATTLE GAP dial; **Qualifying/Sprint Qualifying** uses the eight keys for
individual drivers on timed laps and blanks the gap dial. Practice, testing,
unknown or ended sessions and an unavailable API blank the dynamic keys and dial.
Hidden dial rotations are ignored. Session type comes from `SessionInfo.Type`,
so historical sprint races named “Sprint Qualifying” still behave as races.

Qualifying keys show the **current elapsed lap time** (`m:ss.s`) with the driver
portrait and team outline. The timer follows MultiViewer's native lap-start
timestamp and playback clock, including pause, replay speed and seeks; it updates
with the one-second shared poll. Yellow means the latest reported mini-sector
was not a personal best, green means personal best, purple means session best.
These are the feed's mini-sector judgements while the lap is unfinished, not a
prediction that the complete lap will be a personal or session best. Before the
first reported mini-sector the time is neutral; missing clock/lap-start data
shows `—` instead of substituting the previous lap time.
Mercedes, Ferrari, Red Bull Racing and McLaren take priority, then other teams;
within each group drivers follow timing position, with at most eight shown.
Pressing a qualifying key makes the same driver call as the XL driver board,
following its current target/rotate mode and window/fullscreen behavior.
Detection requires explicit on-track flags and a readable native status; pit,
pit-out, out-lap, stopped, retired and knocked-out drivers are excluded. These
are timed-lap candidates: MultiViewer 2.8.4's private telemetry-based hot-lap
classifier is not exposed through this API, so an unflagged cool-down lap can
still appear. No pace threshold or predicted finishing time is invented.

The rightmost two + XL columns (7 and 8 of 9) are eight live battle keys: four
rows, each pair showing one on-track fight. The leading driver is the left key of
a row, the trailing car the right. Rows are ranked **by position, from P1 down**,
so the fight for the lead is on the top row and a tighter fight further back does
not displace it. Each key carries the driver's 2026 headshot and acronym,
and the team colour as its outline. One number fills each key, at up to 62pt: the
leading driver's key shows the **position** it is defending, the trailing
driver's key shows the **gap** it is closing. That keeps a row readable as one
fight — big white position on the left, big coloured gap on the right — while
either key still answers "who, and how close" on its own.

The gap follows a three-step scale: **green** at a second or more, **yellow**
below a second, **red** below five tenths. The colour is taken from the number as
displayed, so the reading and the warning can never disagree. Pressing a key picks
that driver on either deck: it makes the same call as the XL's own driver
selectors, so the target and rotate keys on the + XL steer it exactly as they
steer those. During a race, keys with no fight show **NO BATTLE**. Qualifying
keys without a candidate show **NO FLYING LAP**; unavailable timing blanks them.

`tools/f1_battles.py` shares one timing read per second for the visible F1 page's
session, keys and track-status edges. Qualifying adds one shared read of
`/api/v2/live-timing/clock` per poll for the native playback speed, which the
GraphQL legacy clock omits. Leaving that page clears cached driver
targets and stops all API reads. While the page is visible, a lightweight local
port probe checks API availability; unavailable or failed APIs retry after five
seconds without running timing detection. A pair counts as a battle when the trailing car is within the
dialled gap (two seconds by default) of the car ahead and the feed flags it as
catching — the feed's own conservative notion of closing, kept in preference to a
gap history this repository would have to invent. In practice that flag marks a
car gaining sustained ground, so a queue of cars running nose-to-tail inside the
window without any of them pulling away is not shown; turn the dial up if that is
too quiet, or down to see only the pairs that are about to be resolved.

**A battle stands for two laps (`HOLD_LAPS`) after the last time it was
closing.** Read instantaneously the feed blinks: the catching flag drops for a
second, the gap crosses the width, and a key that vanishes and returns is worse
than one that outlives the fight. So a pair that has closed at some point in the
last two laps keeps its row, drawn with its **live** gap, whether or not it is
closing right now. Two laps of not closing is long enough to call the fight off.
Only that judgement is held — the readings are not. A car that pits, stops or
retires leaves at once, and so does a pair that stops being consecutive in
position; a lap count that goes backwards is a new session, and nothing carries
over. The age is measured on the **leader's** lap, not either car's, so an
overtake between the two does not restart it. If the feed cannot be read at all
the rows stay empty, but the holds are kept, so a moment of unreadable timing
does not restart every fight on the deck.

The trade-off of holding a pair is that a fight that is genuinely over keeps a
key for up to two laps, and because rows are ranked by position a held pair at
the front takes the top row from a live fight behind it. The gap shown is always
the live one, so the number says what is actually happening even while the row
lingers.

Cars in the pit, stopped or retired are not on-track
battles and are never shown. Running `python tools/f1_battles.py` prints the
current fights under the current width and the same holds the deck uses, without
touching playback; `--fullscreen TLA` does exactly what a
fullscreen toggle does; `--show-onboard TLA` is a standalone helper that ensures
fullscreen. Both commands change playback; diagnostics without either flag do not.

F1 page's rightmost + XL dial (BATTLE GAP) sets that width in tenths of a second,
from 0.5s to 5.0s, showing `2.0s` and a BATTLE WIDTH meter on its touch strip in
the same shape as the audio meters; the bar spans the dial's whole range. The
stored value is a per-workstation preference, not repository configuration:
`~/.cache/opendeck-agents/f1-battles/gap-limit`, private to the user (0700/0600),
written atomically. A missing, unreadable or out-of-range file falls back to two
seconds. A twist is answered on the strip immediately, and the keys pick the new
width up on their next poll, so a wider setting can reveal a fight that the
previous second did not show. Taps and holds on this dial are unassigned.

### Track status on the Formula 1 pages

Both decks' Formula 1 pages show the race director's status. While the track is
under a **yellow flag, a safety car or a virtual safety car** — including the lap
the virtual safety car is withdrawn on — every key on the page takes a **yellow**
edge; a **red flag** makes that edge **red**. The edge is deliberately quiet: it
is 10 pixels around the outside of a key, and the art, the driver, the glyph and
every number on the key are left exactly as they were, because a safety car can
last a third of a race and the deck still has to be usable during it. With the
track clear the edge is simply not drawn: every key is drawn as soon as its page
is shown, with a clear track sending the key's own art unchanged, because the app
keeps the last image it was sent and a deck restarted under a flag would otherwise
hold that mark until the next one.

The plugin reads this topic in the same page-scoped response as session and
driver timing, rather than polling a second monitor. A closed MultiViewer or
unreadable feed clears the edge, never leaving a colour from the last reading.

The page's keys carry the race director's status because only this plugin's own
keys can be written to — the app refuses image writes aimed at another plugin's
key — so the page's commands now run through the plugin instead of the app's run
command action. They are the same commands and they run the same way, from the
repository with its virtual environment. Two things follow: their commands live in
`opendeck-layout.json` rather than in the app's key inspector, and a key press
needs the live-status plugin loaded. The navigation key is the exception — it is
still the app's, and it stays unmarked.
