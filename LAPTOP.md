# Portable + XL coding rig

This preset is for the existing + XL, serial `AD4MA61312Z98B`, used alone.
It opens on **Laptop Vibecoding**: existing telemetry, response, dictation,
Spotify-first/Suno playback keys and all six agent model/reasoning dials retain
their positions and identities. Studio keys are empty. Back opens **Laptop
Navigation**, which links to Vibecoding and **Local Controls**. Local Controls
has PC output, Spotify, terminal font, window zoom and mic input on their existing
dial positions; dial 3 (the former OBS dial) is empty. Play/Next are also available.
No OBS, lights, mixer, Formula 1, Docker demo or completion-sound service is required.
The shared Python plugin still contains its desktop adapters, but the laptop
profiles expose no studio actions and do not request OBS connections.

## Prepare on the desktop

Export includes the current files, including uncommitted work, selected icons,
and saved/live key labels. It excludes credentials, histories, grants, caches,
virtualenvs, machine settings, desktop profiles, private backups and media.
It does not change the desktop layout, installed profiles or running processes.
Let OpenDeck save any label changes before exporting.

```sh
python3 tools/portable_opendeck.py export portable-dist/streamdeck-laptop.tar.gz
```

Copy that archive to the laptop. Use a new filename for subsequent exports;
existing archives are not overwritten. `export-manifest.json` records each
exported source file's SHA256. Keep one copy of the source as the layout authority;
exporting is an explicit snapshot, not bidirectional synchronization. Laptop
label edits persist locally and are preserved on reinstall. Copy those edits
back deliberately if you want them on both machines.

## Install on the laptop

Extract into a permanent directory owned by your normal desktop user. Generated
launchers and agent hooks use that location; rerun profile/integration installation
if you move it. Do not copy a virtualenv between computers.

```sh
mkdir -p "$HOME/workspace"
tar -xzf streamdeck-laptop.tar.gz -C "$HOME/workspace"
cd "$HOME/workspace/streamdeck-laptop"
sudo apt install python3-venv python3-yaml python3-gi gir1.2-atspi-2.0 \
  gir1.2-gtk-3.0 xdotool x11-utils libglib2.0-bin xdg-utils zenity \
  pulseaudio-utils fonts-dejavu-core gnome-terminal
python3 tools/portable_opendeck.py bootstrap
```

Use an **X11/Xorg** GNOME session, GNOME Terminal, native OpenDeck and its
**OpenDeck Starter Pack**. USB access must work in OpenDeck first. The known
working OpenDeck version is **2.14.0**. Its + XL touch workaround is version-gated;
do not bypass the gate on another version without checking native support.
Match the desktop's agent versions for initial migration: these integrations use
private/native interfaces. The tested Claude picker is 2.1.274. Agent logins and
histories belong to the laptop; authenticate there normally.

The focused Codex dial adapter requires both GNOME accessibility preferences.
These commands explicitly enable them; the installer/doctor never changes them:

```sh
gsettings set org.gnome.desktop.interface toolkit-accessibility true
gsettings set org.gnome.desktop.a11y.applications screen-reader-enabled true
```

Initialize whichever CLI agents you use before installing their integrations.
Install independently, or use `--agent both` once both configs exist:

```sh
python3 tools/install_cli_agent_integration.py --agent claude
python3 tools/install_cli_agent_integration.py --agent hermes
```

This adds hooks/statusline support or the Hermes plugin with configuration backups.
Start new CLI sessions afterwards; never stop an active turn just to reload a
plugin. Default Hermes installation is `~/.hermes` (checkout in
`~/.hermes/hermes-agent`, bundled runtime in `~/.hermes/tools`) and
configuration is `~/.hermes/config.yaml`. Nonstandard Hermes locations are not
currently supported by the presence adapter. Codex's bundled executable defaults
to `/usr/lib/chatgpt/resources/codex`; override only if needed with this ignored,
machine-local `portable-machine.json`:

```json
{"codex_executable": "/absolute/path/to/Codex/resources/codex"}
```

Quit OpenDeck completely, then install and check:

```sh
python3 tools/portable_opendeck.py install
python3 tools/portable_opendeck.py doctor
```

The installer builds fresh profiles at the current location, backs up the **entire
OpenDeck configuration**, and preserves other named profiles. It selects Laptop
Vibecoding on the + XL. The existing desktop installer intentionally does not
accept this alternate layout; use the portable command. `--config PATH` goes
before the subcommand for an alternate OpenDeck config directory. This does not
make Flatpak hardware/desktop access equivalent to the tested native installation.

Launch OpenDeck normally from the logged-in desktop. Connect the + XL, check the
three pages, telemetry, model labels, focus targeting, and physical dial/touch
operation. The doctor is read-only and can run with OpenDeck open; a successful
report does not prove live agent protocol compatibility or hardware behavior.
No tool here tests real approvals, Auto Session, model changes, playback or volume
changes automatically. Histories and graphs start from the laptop's local data.

## Update and rollback

To update, save the laptop `opendeck-labels.json` outside the checkout first,
extract the new export over the laptop source, then restore that saved labels file.
The export does not contain machine settings, so those remain in place.
Recreate/install Python dependencies if changed, quit
OpenDeck and rerun `install`. Refresh selected agent integrations if changed.
For relocation, remove this bridge's old Claude hook entries before reinstalling
at the new path, so old-path hooks do not remain alongside new ones.

To roll back, quit OpenDeck and restore the printed full configuration backup.
If runtime code also changed, restore the previous exported source at its former
location. Restore only this bridge's Claude/Hermes configuration from its backups
as needed, preserving subsequent unrelated application changes.

For isolated generation without installation:

```sh
python3 tools/portable_opendeck.py build --output /tmp/opendeck-laptop-check
```
