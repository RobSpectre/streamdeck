# Working on this OpenDeck setup

## Scope and approach

This is a workstation configuration repository, not OpenDeck itself. Read
README.md for operator behavior before changing controls. The canonical layout
is `opendeck-layout.json`; title overrides are `opendeck-labels.json`; generated
profiles/assets/plugin launcher are under `opendeck/`. Preserve the user's live
label edits and unrelated application configuration.

The approach used here was to inspect the installed application code, existing
profiles and local schemas; build narrow adapters; test with synthetic data;
then install with backups and verify in the real desktop. Prefer native
structured state and request IDs to screen scraping or global keystrokes. Keep
Hermes core untouched: its integration is a plugin. Extend the existing SVG icon
style and Pillow telemetry renderer rather than generating unrelated assets.
Do not turn observed shortcomings into undocumented guesses about metrics.

The repository uses X11, GNOME Terminal and workstation-specific paths. Before
claiming a fix is live, distinguish source edits, installed copies and code
already loaded in a running process. A Hermes restart is required after plugin
changes; do not terminate an active user turn to reload it. Never exercise real
Approve/Deny, Auto Session, mixer toggles or purchases as a test without an
appropriate explicit request. Read-only diagnostics and synthetic tests are the
normal verification path.

## Files and runtime architecture

| Component | Role |
| --- | --- |
| `tools/build_opendeck.py` | Layout → native profiles, bundled hashed icons, plugin manifest/launcher, migration report; imports live labels by default |
| `tools/install_opendeck.py` | Requires OpenDeck stopped and Starter Pack present; backs up profiles, captures labels, copies bundle, removes known retired filenames |
| `tools/opendeck_status_plugin.py` | OpenDeck registration/WebSocket, visible key contexts, snapshots, actions and rendered image updates |
| `tools/label_overrides.py` | Stable `label_id` title persistence; excludes intentional state labels/dynamic telemetry |
| `tools/codex_attention.py` | Internal Codex IPC follower, pending-input detection and scoped command/file approvals |
| `tools/codex_telemetry.py` | Codex usage/quota readers plus shared formatting, percentage warnings and Pillow renderer |
| `tools/agent_telemetry.py` | Claude/Hermes local history and unified displayed metrics |
| `tools/cli_agent_bridge.py` | CLI snapshots, pending dialogs/questions, request-bound decisions, scoped grants, Claude hooks/statusline |
| `integrations/hermes-opendeck/` | Installed Hermes plugin source: lifecycle hooks, native UI observation, approval transport and questions |
| `tools/codex_pedal.py` | Shared physical response routing and focused Codex shortcuts |
| `tools/agent_navigation.py` | Existing window/tab focus and account URLs from `agent-navigation.json` |
| `tools/codex_turn_sounds.py` | Independent read-only history watcher; user service in `tools/codex-turn-sounds.service` |
| `audio_controls.py`, `control_obs_*.py`, shell helpers | Existing broadcast/audio actions; audio indicators are tracked state, not mixer telemetry |

The live plugin lazily starts collectors when the relevant key types appear.
It polls sources approximately once a second while keys are visible, invalidates
after key/settings events, and sends changed images/states only. Red telemetry
frames update at 8 fps with 16 phases per two-second pulse. The 256-entry render
cache includes the value tuple and phase. Separate collector threads scan Codex
history every 2 seconds, CLI history every 5, and Codex quota every 60. Instantiated
collectors remain background threads but sleep on the shared `agent_presence`
condition when their agent is closed or its telemetry keys are hidden. Presence
checks run every five seconds (one process scan and listening Unix socket table).
In-flight reads may finish. History offsets survive sleep; retained totals are
labeled cached while offline and do not age until the next collection. Approval
IPC is independent of page visibility and waits for Codex presence before connecting.
The generated launcher waits in two-second intervals for the repo venv/script.

Vibecoding (page 3) is profile index 2; broadcast is index 0. XL serial `CL37L2A01125`; pedal `A00YA5362L663L`.
Zero-based telemetry slots: Codex 1–6, Claude 9–14, Hermes 17–22. Each row is
activity/speed/context/session/month/quota. Vibecoding navigation is slots 0 (previous) and 7 (next). Broadcast keeps
its original positions, including Mic at 0 and the warm-light control at 31. Audio Mode 16;
Deny/Approve/Auto Session/Allow Tool/Dictation 24–28; Codex/Claude/Hermes
overlay copies 29–31 share broadcast page 1 action and label identities. Pedal slots 0/2 deny/approve.
Retain source button identities when moving keys so labels and action state follow.

## Codex telemetry: exact sources and semantics

`~/.codex/ipc/ipc.sock` is an internal Unix socket. Frames are little-endian
32-bit length followed by JSON. Initialize as `opendeck-status`; follow local
`thread-stream-following-changed` events and retain owning client IDs. State
messages currently require **version 11**. Apply snapshots or patches with
matching base revisions; mismatch/invalid data reconnects after two seconds.
Only retain `requests`, `threadRuntimeStatus`, `latestTokenUsageInfo`, `updatedAt`,
`id`, and `latestModel`, not full conversations.

- Input detection: runtime flags `waitingOnApproval`/`waitingOnUserInput`, or known
  request methods for command/file/permissions approval, tool user input/option
  picker, MCP elicitation, and plan implementation. Plain prose is not a signal.
- Activity is any followed state's runtime type `active`. WAITING takes priority.
  The displayed model/usage belongs to the active-preferred, latest-updated task;
  multiple tasks can therefore produce a state/model mismatch by design.
- Session total is `latestTokenUsageInfo.total.totalTokens`, falling back to the
  rollout cumulative counter. Context uses `last.totalTokens` and
  `modelContextWindow`, clamped to 0–100%; it is not session-total/window.
- History index: read-only `~/.codex/state_5.sqlite`, `threads` rows updated in the
  last 30 days, including archived rows. Follow `rollout_path` incrementally.
  Consume complete `event_msg` JSONL lines, retaining byte offsets; reset on file
  truncation. `token_count.info.total_token_usage` counters are cumulative.
  Difference successive counters; on first/reset counters use `last_token_usage`
  to avoid attributing inherited fork history again. Keep positive deltas after
  task creation and within the rolling cutoff. Do not add cache/reasoning
  subcounts to `total_tokens`. These are available local records, not API billing.
- Speed: `task_started` begins timing; `task_complete`/`turn_aborted` ends it.
  Sum output deltas / max(1 second, elapsed turn time). Tools and waits count;
  the ended turn's average persists while idle. No instantaneous streaming rate.
- Quota: spawn `/usr/lib/chatgpt/resources/codex app-server --stdio`; initialize,
  send `initialized`, request `account/rateLimits/read`, terminate the subprocess.
  No thread creation or reset redemption. Prefer `rateLimitsByLimitId.codex`,
  fallback `rateLimits`; among unexpired primary/secondary windows select largest
  usedPercent, display `100-usedPercent` clamped. Hide after 180 seconds or expiry.
  Reset-age calculation remains internal but no reset-age key is displayed.

Sound watcher uses a **different** database: `~/.codex/thread_history_1.sqlite`,
`thread_turns(thread_id, turn_id, status)`. Seed seen IDs at startup; only new
terminal IDs play. `completed`→mk64_item_drop.wav, `failed`→icq.wav,
`interrupted`→nothing. Poll every second, invoke `/usr/bin/paplay` synchronously,
mark seen before playback (no retry), skip historical turns on restart. The
service sets `PULSE_SERVER=unix:%t/pulse/native` and runs independently of OpenDeck.

## CLI bridge and Claude telemetry

Cache root is `~/.cache/opendeck-agents/`. Session filenames hash session IDs;
JSON replacement is atomic with mode 0600, directories created 0700, and session
updates use `flock`. Snapshots carry agent/session/PID/timestamps and compact
telemetry. `sessions()` filters dead PIDs. Start/busy sets active; stop/end/error
clears it; heartbeat/status updates preserve activity unless UI fields override.
PID liveness is not a universal freshness guarantee; do not infer a turn from an
open process. Cache data and old grant files can remain on disk after expiry.

Installer expects existing Claude/Hermes config, adds only its hook group where
absent, saves timestamped config backups, and preserves the original Claude
statusline once in `claude-original-statusline.json`. It uses `/usr/bin/python3`
for Claude hooks and system PyYAML for Hermes config rewriting. It currently
assumes the repo path has no shell-sensitive characters/spaces in that hook
command. The plugin's ROOT and sound service path are also explicit; relocation
requires more than `build_opendeck.py --repo-root`.

Claude hooks: SessionStart, UserPromptSubmit, Stop, StopFailure, SessionEnd,
PermissionRequest, and Notification with `idle_prompt` matcher. Discover the
Claude ancestor PID and require a controlling terminal. Statusline receives
model display_name/id, `context_window.remaining_percentage`, `rate_limits` and
freshness timestamp; then invokes the saved prior statusline command.

History: `~/.claude/projects/**/*.jsonl`, complete lines and offsets. Assistant
usage is `input_tokens + output_tokens + cache_creation_input_tokens +
cache_read_input_tokens`. Streaming repeats are deduplicated by message ID,
fallback requestId/uuid, retaining the largest counter. Monthly aggregation
also deduplicates IDs across files. Select active/recent live session, fallback
latest transcript. Session total includes its messages; month filters timestamps
at now minus 30×86400 seconds. Transcript model is a fallback to statusline model.

Claude speed samples the selected session's output counter when a turn is first
observed, then uses output delta divided by elapsed time through stop/current
clock. Early output before that first sample is not measured; very short turns
can have no useful rate. It is an observed average, not a provider metric.
Quota uses fresh `five_hour`/`seven_day` entries, `used_percentage`/`resets_at`,
most-used unexpired window, 180-second freshness. Missing quota displays N/A.
Ordinary Claude questions are not implemented as separate pending question markers.

## Hermes telemetry and questions

Installed copy: `~/.hermes/plugins/opendeck-cli/__init__.py`, enabled by
`~/.hermes/config.yaml`, approval transport `opendeck-cli` with builtin fallback.
Only interactive stdin registers monitoring/observations. Hook mapping:
`on_session_start`→session, `pre_llm_call`→start, `pre_api_request`→busy,
`post_api_request`→usage, `post_llm_call`/`agent_loop_stopped`→stop,
`on_session_end`→end. Error/unfinished stream end also stops.

Hooks alone missed cancelled/finished turns. The monitor finds the live object
whose type is `cli.HermesCLI` via `gc.get_objects()`, retains a weak reference,
and reads it once a second. `_agent_running` is authoritative for actual UI busy
state, including cancellation paths. Read session ID from agent then CLI; publish
`ui_active`, `ui_updated`, `model`, `native_tps`. Collapse snapshots to newest per
PID so `/new` does not leave an older session active. A UI sample under ten
seconds overrides hook activity. Missing live snapshots plus an interactive
`~/.hermes/hermes-agent/hermes` process produces OPEN, not ACTIVE; gateways are
excluded. Private host fields are upgrade-sensitive; do not monkeypatch Hermes.

Throughput must match Hermes: align the last min(lengths) of agent
`_api_output_history` and `_api_latency_history`, sum outputs / sum latencies.
Reject empty/nonpositive latency or nonfinite rates, display integer tokens/sec.
Do not use turn wall time or an unweighted mean of individual request rates.
`RESTART HERMES` means a live snapshot lacks the native_tps field;
`NO API SAMPLES` means the current plugin has no usable samples yet.

Context: `pre_api_request.approx_input_tokens` plus context length from Hermes'
`agent.model_metadata.get_model_context_length`, respecting model/base URL/provider
and explicit config override. Cache resolver results by those inputs.
Post-response `usage.total_tokens` updates context used. Never hardcode a guessed
window from a model name. Remaining = 100×(1-used/limit), clamped and rounded.

Usage: read-only `~/.hermes/state.db`. Prefer live session, fallback latest root
session with messages. `session_model_usage` covers main and auxiliary/model/task
usage; sum **uncached input + cache_read + cache_write + output**. Reasoning is
already part of output. Include legacy root `sessions` counters only when no
main ledger row (`task=''`) exists. Session counts filter matching session_id.
30-day sum includes ledger rows first_seen within cutoff. A nonzero row with
first_seen before but last_seen after cutoff is excluded and marks the display
`≥`: aggregate counters cannot yield exact daily attribution. Do not query a
Nebius billing endpoint or claim these are account-wide totals; none is wired.

Native clarification detection reads `_clarify_state` and `_app.loop` in
`QuestionMonitor`. Publish an expiring (3-second) `kind=question` marker refreshed
every second, `extended=False`, `allow_tool=False`. Signature includes state
identity, batch active question, question text, selection, checked indices,
freetext mode and draft text. Changes retire the request ID. No question text
or typed answer is copied into the marker.

A physical decision writes a request-specific file. The monitor consumes it and
schedules on `app.loop.call_soon_threadsafe`, rechecking the signature before
acting. Approve calls native `_tui_enter_clarify_choice` or
`_tui_enter_clarify_freetext`; empty free text stays unanswered. Batch questions
advance through native handlers. Deny queues Hermes' native cancellation string
("The user cancelled. Use your best judgement to proceed."), tears down that
question and invalidates the UI. Deny does not interrupt the agent. Never enable
Auto Session/Allow Tool for clarification questions.

## Response routing and grants

Codex plain responses require focus (class Chatgpt plus Codex user-data instance)
and pending input, with focus rechecked before XTEST Enter/Escape. The UI chooses
the prompt/answer; no universal yes/no interpretation is implied. Dictation uses
the same focus guard and Ctrl+Shift+D.

CLI permission transport creates a unique Zenity title/process and marker under
`pending/`; user presses route only by exact PID/title and stable focus, writing
`decisions/<request>.json`. Timeout denies; inability to show falls back native.
Finally remove files and reap the dialog. Do not send approval keystrokes into
terminals. Hermes must obtain session scope via
`tools.approval.get_current_session_key()`; ApprovalRequest has no session_key.

Shared native-question fallback accepts one pending CLI request of kind question,
only approve/deny, no focused Chatgpt-class window, and no supplied Codex-ready
flag. XL supplies that flag; the standalone pedal starts with None and does not
query Codex before the non-Codex fallback. Document this distinction rather than
claiming all cross-agent ambiguity is globally resolved. Multiple CLI pending
requests cause fallback refusal. Question markers are excluded from focused
Zenity matching.

Codex extended actions require exactly one command/file request and focused
Codex. Send version-1 follower approval to its owner using exact request ID,
`accept` or `acceptForSession`; track sent IDs and disable auto on errors.
Auto Session covers subsequent command/file requests only for selected task.
CLI auto.json is scoped to agent/session/owner; Allow Tool hashes exact Claude
tool/input plus scope or delegates Hermes' native session approval. Dead owners
invalidate grants. These do not rewrite global permission policy. Turning off
Auto Session clears both active Codex auto selection and CLI auto.json.

## Rendering, deployment, and verification

Shared renderer is 144×144 PNG data URI using DejaVu Sans/Bold absolute paths.
Brand colors: white, #d97757, #0000f2. WAITING and remaining percentage ≤10 are
#f26672; ≤20 is #ffd447. Thresholds operate on displayed rounded percentages.
Only border intensity/width pulses. Model labels uppercase, maximum two lines,
fit font 22→12 then truncate with ellipsis at 14 if needed. Don't persist live
rendered text as title overrides or regenerate PNGs for each runtime sample.

For layout/assets: generate, test, stop OpenDeck, install, restart. Standard:

```sh
python3 tools/build_opendeck.py
.venv/bin/python -m unittest discover -s tests -v
python3 tools/install_opendeck.py
```

The install step requires OpenDeck fully stopped. Use `--output /tmp/...` and
`--no-import-labels` for isolated build validation (saved overrides still apply).
`--config` selects alternate installed config; native default is
`~/.config/opendeck`, Flatpak is documented in README. Don't overwrite running
OpenDeck profiles: it may persist old state over your changes. Don't run broad
home installers just to update one copied plugin; back up and update that file.
Reload OpenDeck for its Python changes; reinstall and restart Hermes for its
copied plugin; Claude bridge edits load on hook invocation. Restart the sound
user service separately if its code changed. Preserve desktop environment when
relaunching OpenDeck so display/session bus/audio remain accessible.

Tests use synthetic transcripts, SQLite data, request state, mocks, shell inputs,
and profile structure. Cover cumulative-counter dedup, fork/reset behavior,
cache accounting, context/quota freshness, native throughput weighting, stale
question signatures, grants, focus guards, renderer thresholds and animation.
Run relevant tests for edits, full suite before broad delivery. Tests do not
prove hardware rendering or private API compatibility with a new app version.
Verify installed copies and process load state; never claim a live check from
unit tests alone. Documentation-only changes need source/link/diff review rather
than tests that merely assert wording.

Keep credentials, live transcripts, token caches, permission payloads, desktop
logs and temporary backups out of commits. Inspect git status before staging;
a local `opendeck-layout.json.bak-*` may be present and should remain untracked.
Commit generated assets when the layout changes, but not runtime state. Record
source assumptions and limitations when changing an adapter; if a schema changes,
prefer unavailable data to plausible but incorrect numbers.

## Spotify-first / Suno playback adapter

Vibecoding slots 15 and 23 are `suno_media` Play/Next. The live plugin gives them
static ready state and launches `/usr/bin/python3 tools/suno_media.py <action>`
with a 12-second timeout; failures use its existing showAlert handling. System
Python is deliberate: the workstation's GI/AT-SPI packages are outside the venv.

The helper finds Chrome/Chromium accessibility windows and PAGE_TAB entries with
Suno in their name. Require exactly one candidate; select its native default
action if necessary. Find one DOCUMENT_WEB whose URI has HTTPS and exact hostname
suno.com or www.suno.com. Query PUSH_BUTTON controls by exact observed labels:
`Playbar: Play button`, `Playbar: Pause button`, `Playbar: Next Song button`.
Recheck tab selection and URL, require enabled state, then invoke only the default
action (never showContextMenu). Labels/AT-SPI interfaces are upgrade-sensitive.

Chrome cached children can be None despite populated windows. Set app cache mask
to NONE and use the Collection interface rather than blindly descending children.
Bound AT-SPI calls and let missing/ambiguous controls fail; never fall back to
screen coordinates or global media keys. MPRIS was investigated but Chrome's
session did not identify Suno or offer usable transport capabilities, so it is
not the source of control. No persistent system accessibility change is needed.
`--check` verifies the real tab/control without invoking playback but may select
the tab. Tests cover origin spoofing, exact playbar labels, ambiguity rejection
and default-action selection. Icons do not claim live playback state.

Before Suno discovery, `spotify_control` lists desktop D-Bus names and matches
`org.mpris.MediaPlayer2.spotify` or its dot-suffixed instances. Resolve its unique
owner, read CanControl/CanPlay/CanPause/CanGoNext and PlaybackStatus, and call
PlayPause or Next on that same owner with NO_AUTO_START. Open paused Spotify
still wins. Only absence falls back to Suno; ambiguity, unsupported controls or
errors alert without sending a second-player action. `--check` queries without
playback. The Spotify web player is not identified by this desktop MPRIS rule.
The helper runs fresh for each key press, so editing it needs no OpenDeck restart.

## MultiViewer live-timing battles (+ XL)

The live plugin now uses one page-scoped `BattleFeed` for SessionInfo,
SessionStatus, TimingData, DriverList and TrackStatus. Visibility of an F1 key,
marked art or the gap dial activates it; leaving the page clears cached targets
and holds. A 0.2 s local TCP probe precedes timing reads; unavailable APIs and
failed reads back off five seconds, with no timing detection. Race/Sprint
(`Type=Race`) shows battles and gap dial; `Type=Qualifying` shows up to eight
individual timed-lap candidates and blanks/disables the dial. Practice, unknown
types, ended status and unavailable API blank both. Started/Finished status is
accepted, preserving the final laps before Ends/Finalised. Session Key/Path/mode
changes clear holds even when lap counts increase. Rendering/presses read only
that shared cache; track status no longer has a separate plugin polling loop.

Qualifying candidates require explicit false InPit/PitOut/Stopped/Retired and
integer Status clear of native bits 2/4/16/32/512 (stopped/retired/pit/pit-out/
out-lap); also reject Outlap and KnockedOut. DriverList.TeamName prioritizes
Mercedes, Ferrari, Red Bull Racing and McLaren, then timing position within each
group. Qualifying keys show current elapsed lap time in `m:ss.s`, truncated to
tenths, sampled on the shared one-second poll. `NumberOfLapsTs` is the native
start/finish crossing timestamp: relative milliseconds for replay patches,
absolute UTC milliseconds for live patches. One additional shared GET to
`/api/v2/live-timing/clock` supplies paused/speed/systemTime/trackTime/
liveTimingStartTime; GraphQL's legacy clock omits speed. Extrapolate the anchor
by wall-time delta times native speed only when unpaused, resolving lap-start
domains against the native origin. Missing/nonfinite/negative/future values
yield `—`, not a previous completed lap or a locally invented stopwatch.
The latest contiguous current-lap mini-sector status controls timer colour:
2048 yellow (not improved), 2049 green (personal best), 2051 purple (session best).
Stop at the first zero/unreported segment, excluding later carried-over sectors;
unknown/pit/stopped/retired codes and missing timer data are neutral. These are
mini-sector judgements, not a whole-lap prediction. Keys identify timed-lap
candidates, not a reconstructed native
hot-lap verdict: 2.8.4's private telemetry classifier is not in the public API,
and unflagged cool-down laps can remain. Never invent pace thresholds. Qualifying
presses run `f1_keys.driver` asynchronously, exactly like the XL driver board and
race battle keys, following the existing target/rotate and window/fullscreen
behavior. The standalone `--show-onboard` helper is not the deck press path.

The eight battle keys are `live_control` kind `f1_battle`, slots 0–7 in reading
order (slot even = leading driver, odd = trailing). `tools/f1_battles.py` polls
`liveTimingState { TimingData DriverList }` over MultiViewer's local GraphQL API
once a second while those keys are visible; the poll loop renders each key from
one shared cached read, and a press reads that same cache rather than refreshing,
so a key always fullscreens the driver it was showing. Unchanged renders are not
re-sent. Detected pairs are consecutive positions where the trailing car's
`IntervalToPositionAhead` parses to a number within the dialled width (default
`GAP_LIMIT` 2 s) and its `Catching` flag is set. `Catching` is the feed's own
conservative notion of closing and is used in preference to a gap history this
repo would have to invent; it fires for far fewer cars than the two-second window
alone, so a nose-to-tail queue with nobody pulling away is legitimately empty.

`battle_pairs()` returns every on-track consecutive-position pair with a readable
gap, **ordered by the leading car's position** so the fight for the lead is the
top row and the deck cannot reshuffle when a gap changes by a hundredth; `closing`
on each entry is the judgement and the rest is a reading. `battles()` is the
instantaneous subset, used by tests. The deck shows `closing` pairs plus the ones
still standing: `BattleFeed.shown(pairs, lap)` keeps a pair for `HOLD_LAPS` (2)
laps after the last lap it was closing on, held in `self.seen` as pair key ->
lap and pruned to the current candidates each poll. Only the closing judgement is
held; a pit stop, a retirement or a lost consecutive position removes the pair
from the candidate list entirely, so it goes at once. `session_lap(timing)` is the
**leader's** lap count (max `NumberOfLaps`), not either car's, so an overtake
between the two does not restart the age; `pair_key()` is the sorted racing-number
pair for the same reason. A lap that has gone backwards is a new session and
nothing stands, and an unmeasurable lap switches the hold off instead of inventing
a clock. A failed read empties the rows but keeps `seen`. Held rows are drawn with
their live gap, so the number never lies about a fight that has ended.

Width is operator state, not a constant: `gap_limit()`/`set_gap_limit()` read and
write `~/.cache/opendeck-agents/f1-battles/gap-limit` (private 0700/0600, atomic
replace, 0.5–5.0 s in whole tenths, default 2.0), and `BattleFeed` re-reads it on
every refresh so a twist takes effect on the next poll. Reads never create the
directory and never raise: an unreadable or out-of-range file falls back to the
default, because the keys must keep drawing whatever happens to the cache. The
value is per-workstation and deliberately outside the repository, so the portable
preset inherits the default.

`+1 LAP` and blank intervals are unknown, not zero, and a car in the pit,
stopped or retired is not an on-track battle. The leader has no interval but
must stay in the order or the fight for the lead is lost. A pair whose position
numbers are not consecutive is never paired — that is what stops a car with a
missing position joining two cars a lap apart. A feed that cannot be read shows
`NO TIMING` (state 2) rather than stale battles.

Key art is drawn by the module's own Pillow renderer from the existing
`images/formula_1/2026/<TLA>.png` headshots cropped to `CROP`; a driver with no
headshot asset (there is no `TSU.png`) keeps the plain card instead of a
fabricated image. `headline(value)` picks the one number a key carries: the
leading driver's key the position, the trailing driver's the gap, each at the
largest bold size that fits, with the acronym above and the team colour as the
outline. `gap_colour()` reads the displayed gap (2 dp), not
the raw feed value, so the colour can never contradict the number: green at ≥1 s,
yellow below 1 s, red below 0.5 s. Titles stay empty: the acronym is in the image,
and `f1_battle` is excluded from label capture and the label sync like telemetry,
so no rendered text is persisted as a title override. `LabelSync.changed` also
refuses every `DYNAMIC_KINDS` title, since the app can report our own title back
as an edit. Pressing makes the same call as the XL's driver selectors,
`python control_driver_feeds.py driver --driver_abbreviation <TLA>`
(`tools/f1_keys.py`), so a driver behaves the same whichever deck picked it and
the `set-target`/`rotate-drivers` keys still steer it. `f1_battles.fullscreen()`
and `onboard_players()` remain that module's own MultiViewer route, reached by its
`--fullscreen TLA` CLI rather than by a key.

The F1 page's rightmost + XL dial is `control` `f1_gap_limit`, handled in
`tools/dial_controls.py` rather than the agent dials: `read` renders the same
touch-strip shape as the audio meters (title, `2.0s`, bar spanning the dial's
range, `BATTLE WIDTH`) and `rotate` returns `{id: feedback}` so the strip answers
the twist immediately instead of waiting for a poll. It is not an audio target,
so its taps and holds are inert.


## Track status on the Formula 1 pages

`tools/track_status.py` interprets the race director's status (`liveTimingState {
TrackStatus }`): 1 all clear; 2 yellow flag, 4 safety car, 6 virtual safety car
and 7 virtual safety car ending are the page's yellow; 5 is red. Any other code
is no status rather than an invented one, and an unreadable feed is clear,
because a finished session or a closed MultiViewer is not a race under a flag.
The plugin obtains it from the shared page-scoped feed described above;
`StatusFeed` remains available for standalone diagnostics and synthetic tests.

A plugin may only write to a key its own action owns — OpenDeck drops a `setImage`
whose target instance belongs to another plugin (`src-tauri/src/events/inbound/
mod.rs`) — so nothing on the page could be marked while its keys were the app's
run-command controls. Every F1 page key is therefore `live_control` kind `f1_key`
now: the same command under this plugin, run by `tools/f1_keys.py` with the
wrapper the app's run command action built for these keys (repository working
directory, its `.venv/bin` ahead of PATH, fire and forget so a key cannot stall
the poll loop). The one key the app still owns is the navigation key, because
only the starter pack may switch profiles; it keeps its normal look.

The builder writes a key-sized copy of each marked key's art into the bundle and
records it in that key's `_track_status` setting. `load_art()` reads a square PNG
directly, and for the two hand-made driver views the top square of the portrait
embedded in the SVG, which is what the app shows. A status is drawn over the art
as a `MARK` (10) pixel edge — `#ffd447` yellow, `#f26672` red — instead of a
background: a flag lasts many laps and the deck still has to be read during one.
Every marked key is drawn as soon as its page is shown, a clear track sending the
art plain, because the app keeps the last image a key was sent: a deck restarted
under a flag would otherwise hold a stale mark until the next one. Repeats are
skipped by the same image cache as the rest of the page, and a status is only
drawn once it is readable — an unreachable feed is clear, never a colour left
over from the last session. The battle cards are marked by their own renderer,
and `track_status.DRAWN` lists the kinds that are.

Consequences of re-homing those keys: their commands are edited in the layout
rather than as Run Command in the app's property inspector, and a press needs
this plugin loaded. Their art, text and labels are unchanged.
