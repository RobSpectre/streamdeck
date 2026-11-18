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
| `tools/hermes_config.py` | Isolated Docker demo terminal and return-to-workstation button; never modifies host Hermes profiles/history |
| `tools/cli_agent_bridge.py` | CLI snapshots, pending dialogs/questions, request-bound decisions, scoped grants, Claude hooks/statusline |
| `integrations/hermes-opendeck/` | Installed Hermes plugin source: lifecycle hooks, native UI observation, approval transport and questions |
| `tools/codex_pedal.py` | Shared physical response routing and focused Codex shortcuts |
| `tools/f1_battles.py` | MultiViewer live-timing battles on the + XL: detection, key art and onboard fullscreen |
| `tools/f1_keys.py` | The F1 pages' key commands and the driver-selector call, run under the plugin |
| `tools/track_status.py` | Race-director track status, and the coloured edge drawn on the F1 pages |
| `tools/agent_navigation.py` | Existing window/tab focus and account URLs from `agent-navigation.json` |
| `tools/agent_compact.py` | Context Left press: compacts the shown session through each agent's own command |
| `tools/claude_compact.py` | System-Python helper typing Claude's `/compact` into its idle terminal, verified before Enter |
| `tools/codex_turn_sounds.py` | Independent read-only history watcher; user service in `tools/codex-turn-sounds.service` |
| `audio_controls.py`, `control_obs_*.py`, shell helpers | Existing broadcast/audio actions; audio indicators are tracked state, not mixer telemetry |

The live plugin lazily starts collectors when the relevant key types appear.
Claude Desktop main-process presence is tracked separately as `claude_desktop`
(exact `/usr/lib/claude-desktop/claude-desktop` executable and comm, excluding
Chromium child roles). Without a linked Code session, its activity key shows
OPEN / DESKTOP · NO TELEMETRY. This is app presence only; it never establishes
active/waiting state, wakes the CLI history collector, or changes approval routing.
Local Code worker detection remains `claude` and takes precedence when linked.
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
The following XL control positions describe the saved standalone travel layout
in `opendeck-xl-travel.json`; the desktop XL now has broadcast soundboard, Formula 1 driver and Vibecoding capsule overflow, without Back.
Zero-based telemetry slots: Codex 1–6, Claude 9–14, Hermes 17–22. Each row is
activity/speed/context/session/month/quota. Navigation is profile index 10 and the default selected page on both screen decks.
Every + XL subpage and saved travel subpage uses slot 0 for Back to Navigation; desktop XL overflow has no Back. Former next-page slots are empty,
except broadcast Mic moves to slot 7 (XL) / 8 (+ XL), preserving its identity.
The warm-light control remains at XL slot 31. Audio Mode 16;
Deny/Approve/Auto Session/Allow Tool/Dictation 24–28; Codex/Claude/Hermes
overlay copies 29–31 share broadcast page 1 action and label identities. Pedal slots 0/2 deny/approve.
Retain source button identities when moving keys so labels and action state follow.

Desktop navigation is paired through each device's `navigation_peer`: the builder
emits native Multi Actions, switching the peer first then the local device.
This applies to navigation keys and Back, not manual editor profile selection.
+ XL ordinary labels are top-aligned; rendered telemetry and dial feedback are
unchanged. XL overflow pages retain bottom labels. Broadcast overflow slots 0–14 copy
the 15 live soundboard effects; slots 16–17 hold Rap Horn and Wrong, sharing
label/action identities. Overflow pages have no Back buttons; use + XL Back
to return both decks to Navigation. Formula 1 overflow slots 0–21 hold 22 driver selectors, all kind
`f1_key`: every key on both Formula 1 pages is this plugin's own control, which is
what lets the track status mark them (see the track status section). The November 7 replacements are HAD (Red Bull), LAW (Racing Bulls) and CAM
(Rafael Camara at Haas, replacing Ocon), in slots 1/3/16. Their upper-body SVG
views embed MultiViewer 2.15.2’s explicit 2026 portraits; CAM.png supplies the
existing battle renderer’s square-headshot format. LIN remains in slot 2 and
BOT/PER occupy 20/21. Other artwork uses MultiViewer 2.8.4’s 2026 assets; provenance is in
`images/formula_1/2026/source.json`. The + XL retains broadcast/playback controls in place and adds
eight live battle keys in its rightmost two columns (zero-based slots 7/8, 16/17, 25/26, 34/35; leader
left, trailer right, rows ranked by position from P1 down; the leader's key headlines its position, the
trailer's its gap, green/yellow/red) and a battle-width dial in its rightmost encoder position;
Formula 1 Page 2’s navigation link is hidden. Vibecoding overflow rows 0–2 each
use columns 0–5 for Codex/Claude/Hermes Model, Spark, Speed, Context, Session,
Month capsule toggles. Slot 24, the bottom row's first key, is the isolated Hermes demo control
(`tools/hermes_config.py`, kind `hermes_config`). State indexes remain 0 = FRESH,
1 = unavailable, 2 = MY CONFIG. It opens/focuses a disposable Docker demo terminal
and switches back by focusing the workstation CLI; it never writes Hermes's
sticky active_profile or resets host data. See README's isolated-demo section.
The image is `opendeck-hermes-demo:1`, built from `integrations/hermes-demo/`.
No host mounts, secret forwarding, desktop bus, or Docker socket enter the demo.
Closing its shell allows the next press to discard that stopped container and
start clean; switching to MY CONFIG does not kill an active demo. Reset refuses
running containers and validates the managed label before deleting an exact ID.
State is cached for five seconds; control state is under the private
`~/.cache/opendeck-agents/hermes-demo/`. Reload OpenDeck after helper edits.
Preserve old named profiles; they are not an install/uninstall safety boundary.
`tools/chyron_capsules.py` preserves browser-source CSS
around marked visibility rules targeting the overlay's data-agent/data-metric
attributes. Companion width rules preserve original capsule sizes using the
overlay's ROW_WEIGHTS, gap, padding and theme borders; hiding capsules shrinks
the card and keeps its left edge fixed. All hidden leaves a compact header.
State reflects the managed preference, independently of on-air state;
it does not disable collection or tally audio. Other overflow pages are empty. The + XL broadcast manual arrangement
was adopted again on September 21; Mic is now at zero-based slot 10. Preserve `opendeck-xl-travel.json` as the pre-overflow standalone
layout, including its `label_overrides`. Build it separately with `--source`
and `--output /tmp/... --no-import-labels`; never overwrite the desktop bundle
with the travel export. The standard installer accepts only the canonical layout.

## Codex telemetry: exact sources and semantics

`~/.codex/ipc/ipc.sock` is an internal Unix socket. Frames are little-endian
32-bit length followed by JSON. Initialize as `opendeck-status`; follow local
`thread-stream-following-changed` events and retain owning client IDs. State
messages currently require **version 11**. Apply snapshots or patches with
matching base revisions; mismatch/invalid data reconnects after two seconds.
Only retain `requests`, `threadRuntimeStatus`, `latestTokenUsageInfo`, `updatedAt`,
`id`, `latestModel`, `latestReasoningEffort`, and compact
`latestCollaborationMode` (mode plus settings.model/reasoning_effort only), not
full conversations or collaboration developer instructions.

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
for Claude hooks and system PyYAML for Hermes config rewriting. Hook command paths are shell-quoted. The installed Hermes plugin reads its
checkout path from private runtime.json. The optional sound service still has
an explicit workstation path; relocation requires regenerating installed
launchers and reinstalling selected CLI integrations.

Claude hooks: SessionStart, UserPromptSubmit, Stop, StopFailure, SessionEnd,
PermissionRequest, and Notification with `idle_prompt` matcher. Discover the
Claude ancestor PID and require a controlling terminal or a Claude desktop-app
session: `cli_agent_bridge.desktop_session()` is the one rule for the hook gate,
presence and focus. The app loads user settings (`--setting-sources=user,...`),
so the hooks already fire there; its sessions never run the statusline. Their
figures come instead from the `opendeck-telemetry` plugin
(`integrations/claude-opendeck`, local marketplace `integrations/`): a hooks
module (early-access function hooks, enabled by `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`
in `~/.claude/settings.json` `env`; no other installed plugin ships a module)
observing `session.measure` and writing `claude-measure/<uuid>.json`.
`sessions()` merges it in the statusline's shape (tokens/window, else 100-percent;
`rateLimits` → `rate_limits`, `measured` → `quota_updated`) when newer than the
statusline's reading, so the 180 s quota freshness is unchanged: Claude quota
shows while a turn has reported `five_hour`/`seven_day` in the last 3 minutes and
is N/A otherwise. A run's first measurement can lack rate limits. The model name is the transcript `model` attachment's `marketingName` when
its `modelId` is the latest reply's; effort comes from hook payloads' `effort.level`.
Test the mod with `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude plugin test
integrations/claude-opendeck` and `claude plugin validate`; plugins load at session
start, so edits need a reinstall/update and a new session. By the user's
choice their PermissionRequest goes to the Zenity dialog, not the app's prompt,
so a false positive would capture an SDK app's approvals: keep the rule strict.
Focus activates the window whose `_NET_WM_PID` is the session's parent; the
dials show them (`$.session.model()` via the mod, `model_label()`, hook effort)
as DESKTOP · VIEW ONLY and never change them: typed `/model` saves a global default. Statusline receives
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
Hermes process produces OPEN, not ACTIVE; gateways (no terminal) are excluded.
`agent_presence.hermes_cli()` is the one identity rule for presence, OPEN and
focus. The September launcher execs `~/.hermes/tools/python-*/bin/python3 -I -c
<bootstrap>`, so no launcher path is in argv[:2]; Hermes' main() sets comm to
`hermes`. Match that comm plus `/proc/PID/exe` inside the resolved `~/.hermes`,
or the legacy `~/.hermes/hermes-agent/hermes` in argv[:2]. The exe test is what
keeps the Docker demo (also `hermes`, also on a TTY) from counting; never match
comm alone. Private host fields are upgrade-sensitive; do not monkeypatch Hermes.

Throughput must match Hermes: align the last min(lengths) of agent
`_api_output_history` and `_api_latency_history`, sum outputs / sum latencies.
Reject empty/nonpositive latency or nonfinite rates, display integer tokens/sec.
Do not use turn wall time or an unweighted mean of individual request rates.
`RESTART HERMES` means a live snapshot lacks the native_tps field;
`NO API SAMPLES` means the current plugin has no usable samples yet.

Context: the UI monitor samples `agent.context_compressor.last_prompt_tokens`
and `context_length` once per second. New gateway-backed CLIs mirror native
`session.usage` into this view; their API hooks run outside the interactive
process. Missing/nonfinite values, a negative post-compression sentinel, or a
nonpositive window stay unavailable. This is last-request prompt usage, not the
status bar's optional anchored conversation estimate. Existing in-process API
hooks still publish request estimates/usage, but the UI sample is authoritative
on its next tick. Never infer a window from a model name or re-read a global
override instead of the live resolved window. Remaining = 100×(1-used/limit),
clamped and rounded. Restart Hermes after this plugin change.

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

## Compaction from Context Left

A Context Left press compacts the session that key shows, with one tap and no
confirmation (the user's choice). `codex_telemetry.displayed_thread()` and
`agent_telemetry.displayed()` are the one selection rule for image and press.
Every path refuses rather than interrupts, and the press alerts on refusal.

Codex: version-1 `thread-follower-compact-thread` `{conversationId}` to the
task owner; require `{ok: true}` within 4 s. The owner runs the compaction its
own UI offers (`thread/compact/start`); never start a second app-server on a
live thread. Refuse an active task or one waiting on input.

Hermes: the deck writes `compact-requests/<32 hex>.json` (pid, session, 3 s
expiry). `ModelMonitor.compact()` in `hermes_model_dials.py`, which the installed
plugin loads from the checkout, takes only its own PID, drops expired requests
silently, rechecks session, `busy()` (running or any native panel) and a pending
model switch, then puts `/compress` on `cli._pending_input`. The REPL worker
dispatches it like a typed command; the input buffer and any draft are untouched.
`compact-results/<hex>.json` carries the status; anything but `queued` alerts,
and no answer in 3 s means a Hermes started before this code: restart it.

Claude has no command channel. `claude_compact.py` (system Python, AT-SPI)
focuses the session's own GNOME Terminal and rechecks the claude_dial focus and
foreground-session match before every key. The input box is a `>` line directly
under a `╭───` or `────` rule; `❯` is a menu cursor and never counts. Type
`/compact`, press Enter only if the box then reads exactly that, else BackSpace
×8 restores any draft. Refuse vim editor mode, a remapped Chat `enter`, an open
model picker, or no input box. Desktop-app sessions refuse until an AT-SPI
adapter exists: with GNOME accessibility off the app exposes no web content.
Never exercise real compaction as a test. OpenDeck reload for `agent_compact`,
`codex_attention` and plugin edits; Hermes restart for `hermes_model_dials`;
`claude_compact.py` runs fresh per press.

## Rendering, deployment, and verification

Shared renderer is 144×144 PNG data URI using DejaVu Sans/Bold absolute paths.
`tools/telemetry_graphs.py` stores raw observed samples in private
`~/.cache/opendeck-agents/telemetry-graphs.sqlite`: 120 five-second buckets for
speed/context/session, 144 ten-minute buckets for month. Collection follows
visible telemetry and agent presence; missing periods are gaps, with no backfill.
`values(..., samples=...)` supplies raw numbers separately from display tuples.
Task scopes are hashed and changes break lines. Context scale is 0–100, TPS
zero-based, totals use the observed range.
TPS graph samples use the selected session's active average, zero for confirmed
idle, and None for unknown/offline. The numeric readout still retains its average.
Graph DB version 1 discards legacy TPS rows whose activity was not recorded,
preserving context/session/month history.
Render cache keys include graph tuples; backgrounds stay fixed during
warning-border animation. These graphs are for
hardware telemetry keys, not the chyron capsules.
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

## Broadcast + XL encoders

Device AD4MA61312Z98B has six broadcast dials in source `dials["0"]`:
PC output, Spotify, OBS XAir, focused terminal font, focused window zoom, mic input.
The Formula 1 page (`dials["4"]`, position 5, the rightmost) holds only the
battle-width dial, so the broadcast arrangement is unchanged.
`tools/dial_controls.py` reads actual volume settings and applies bounded rotations;
`tools/dial_desktop.py` uses system Python GI for Spotify MPRIS and terminal GTK actions.
Meters are volume settings, not measured signal levels. Font/zoom numeric readouts
are unavailable; never infer them from a counter of shortcuts. See README for
supported window classes and focus-race limitations. In Studio Audio, touch taps toggle mute for the four audio targets; holds, knob presses and font/zoom taps are unassigned. TV Audio is described below. Spotify mute resolves exact `spotify` process-binary metadata on sink-inputs or their owning PipeWire clients, with one process owner, preserving MPRIS volume. No stream means unavailable for mute.
OpenDeck 2.14.0 native `Encoder` contexts and `setFeedback` use generated
`party.hack.status.sdPlugin/dial-meter.json`; include this and the manifest during
installation, then reload OpenDeck. Synthetic tests must not alter real volumes.


## Broadcast television audio view

The + XL broadcast keys at slots 24/33 select `dial_view` studio/television in
place. `Dials.effective()` applies the four middle dials' `television` settings;
PC output and mic input stay at 0/5. Studio is the process-start default. A view
switch never changes audio or stored profile settings. TV `dialDown` and short
`touchTap` solo the selected feed; ignore `dialUp` and holds, preserving the
Studio view's unassigned knob presses. Rotations adjust only the bound stream.
The four view-switching encoder states must have empty `text`: OpenDeck 2.14.1
`encoder_layouts.rs::get_encoder_image` uses nonempty state text as a title
override above `setFeedback.title`. Keep Studio/TV names in settings and live
feedback; do not put fixed Studio titles back into these native state objects.

`tools/television_audio.py` uses pactl and private runtime bindings, not Chrome
accessibility (the user explicitly chose to leave it off). All four players
must be browser-unmuted; PulseAudio mute keeps three inaudible. An approved live
test confirmed four distinct streams when all four YouTube TV players produce
audio. Every stream has Chrome's shared audio PID and media.name Playback, so
PID/name/order are not tab identity. Calibrate stream/window pairs explicitly;
bind stream/client indices, PipeWire object.serial, PID/start time/boot ID, and
the exact Chrome YouTube TV X11 window. Recheck before each write; validate all
four, mute the others, verify their mute states, then unmute the selected feed.
Refresh/replacement requires rebind rather than guessing. The `learn` command
requires the operator to unmute only the intended player and rejects multiple
new Chrome streams. Runtime bindings never enter the repo. See README.

## Adopting manual key positions

`tools/import_opendeck_positions.py --write` adopts saved native OpenDeck key
positions into the canonical layout by stable `_label_id`. It matches across
pages within the same device, preserves source actions and dial settings, and
fails on unknown/ambiguous identities or changed key counts. It backs up source,
labels and native profiles under private `/tmp/opendeck-positions-*`. Regenerate
and compare every key identity/empty slot against native profiles afterward.
Do not reinstall over live edits just to adopt them. September 18, 2026 manual
+ XL arrangements supersede the initial eight-to-nine-column copying rule.


### + XL touch compatibility

OpenDeck 2.14.0 `elgato.rs` dispatches touch only for `Kind::Plus`, dropping
`PlusXl`. `tools/plusxl_touch.py` reads only this serial's hidraw input and
forwards fresh visible-dial short taps through native `touchscreenPress` events.
Verified physical packets use x=0..1199, y=0..99; slot=x//200. HID layout follows
elgato-streamdeck 0.13.1 `util::read_lcd_input`. Ignore holds/swipes; never write
HID reports. Reader is package-version-gated to 2.14.0, runtime-lock protected,
and stops with the live plugin. Do not loosen the version gate without checking
for native support (otherwise taps can toggle twice). See README for details.

## Focused agent model dials (+ XL Vibecoding)

`tools/agent_dials.py` handles the six white/orange/blue model/reasoning sections;
`agent-selector.json` is a 200×100 pixmap layout. `tools/agent_dial_desktop.py`
keeps one system-Python accessibility connection. Rotations never change focus;
strip taps focus the agent via `agent_navigation.focus_agent`. An unfocused
Claude tap only focuses; an already-focused idle Claude tap retains native
session-only picker confirmation. Busy taps do not submit keys.
`tools/agent_dial_focus.py` matches Codex's active document title against the
unique local `coalesce(nullif(name,''),title)` task display name. GNOME terminal
matching uses native screen UUIDs; duplicate titles additionally require a unique
native SearchProvider visible-text snippet match. Snippets are transient opaque
comparisons, not instructions, telemetry, or persisted/logged text. Cache only native accessibility object handles, clearing their property caches
and rereading active state/document title on every focus check. Recheck focus
before writes; reject ambiguity rather than picking the most recent session.
Compare the focused task and effective model/effort across the recheck, not full
conversation snapshots: token/updatedAt changes are normal during active turns.
Use the fresh state for native request conditions. This Codex build requires
GNOME toolkit-accessibility and screen-reader-enabled support to expose its
task document. Both workstation preferences are enabled; the plugin does not
toggle global settings. A missing document reports ENABLE ACCESSIBILITY.
Codex dial feedback is sent immediately after acknowledgement, ahead of the
ordinary telemetry poll; do not present unconfirmed settings as applied.

Codex uses read-only app-server `model/list` for supported efforts, version-11
stream fields `latestModel`/`latestReasoningEffort` plus compact
`latestCollaborationMode.settings`, and the **version-2**
`thread-follower-update-thread-settings` request. Send only model/effort,
`activeTurnId:null`, and expected model/effort conditions. This is next-turn,
task-scoped state, not a new turn or saved global defaults. Wait for confirmation.
Display/rotation prefer the collaboration-mode settings, matching the composer;
legacy latestReasoningEffort can be null while composer effort is medium. Never
substitute the model catalog's low default for that value. Explicit null displays
DEFAULT and does not give reasoning rotation an invented starting level.

Claude 2.1.274's native Alt+P picker provides model-dependent effort choices.
Rotations preview with Up/Down or Left/Right; a strip tap sends `s` to apply to
this session. Never use Enter or `/model <name>`: those save a default. Require
an idle live foreground CLI, stable focused tab, recognized picker footer, and
compatible keybindings. Statusline effort comes from `effort.level`.

`tools/hermes_model_dials.py` is loaded by the Hermes plugin. It publishes
short-lived model catalogs/current settings, consumes expiring commands bound
to PID/session/settings signature/focus, and invokes the native session-only
switch and confirmation functions. One switch worker at a time; no busy turns
or pending dialogs. Nebius efforts are derived from its pure native kwargs
adapter and canonical ladder, not inferred from a model name in this repo.
OpenRouter/Nous use their explicit serving-catalog ladder before models.dev;
the native reader is case-sensitive, so retry a lowercase ID only when the exact
lookup is unknown. An explicit unsupported verdict is never overridden. Warm
the native catalog asynchronously; the monitor's lookup stays cache-only.
Unknown provider capabilities remain unavailable. Restart Hermes after copying
the plugin; never terminate an active turn for reload. Native interfaces are
upgrade-sensitive. Unit tests don't establish that physical rotations work.


## Portable + XL laptop preset

`opendeck-laptop.json` is the standalone coding-only + XL preset; retain existing
key/action identities when updating it. No navigation peer or studio controls.
`tools/portable_opendeck.py` exports an explicit source/asset allowlist including
uncommitted code, builds locally, performs read-only diagnostics, and installs
with a full OpenDeck configuration backup. Use its installer for this preset;
the canonical installer remains desktop-only. See LAPTOP.md.
`requirements-laptop.txt` excludes studio dependencies. The live plugin tolerates
a missing lights.json. Machine-local `portable-machine.json` optionally overrides
the Codex bundled executable. The CLI installer now supports --agent selection,
quotes hook paths, and writes the Hermes checkout path to installed runtime.json.
Source Hermes imports derive their root from __file__; no desktop path is baked in.
