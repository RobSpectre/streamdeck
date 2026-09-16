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
collectors remain background threads; hiding a page is not a shutdown mechanism.
The generated launcher waits in two-second intervals for the repo venv/script.

Page 6 is profile index 5. XL serial `CL37L2A01125`; pedal `A00YA5362L663L`.
Zero-based telemetry slots: Codex 1–6, Claude 9–14, Hermes 17–22. Each row is
activity/speed/context/session/month/quota. Navigation is 0 and 7; Audio Mode 16;
Deny/Approve/Auto Session/Allow Tool/Dictation 24–28. Pedal slots 0/2 deny/approve.
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
