# Demo-only shell: never sourced on the workstation.
[ ! -f "$HOME/.bashrc" ] || source "$HOME/.bashrc"
export PATH="$HOME/.local/bin:$PATH"
PS1='\[\e[1;34m\]HERMES DEMO\[\e[0m\] \w \$ '
printf '\nHermes demo — disposable container, separate from your workstation.\n'
printf 'Run hermes to set up/chat, or install-hermes to demonstrate installation.\n'
printf 'No workstation files, credentials, Docker socket, or desktop sessions are mounted.\n'
printf 'Exit this shell when finished; the next demo starts clean.\n\n'
