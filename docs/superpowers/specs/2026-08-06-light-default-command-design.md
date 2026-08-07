# `light_default` Command Design

## Goal

Provide a `light_default` command that can be run from any directory to restore
the Logitech G560 lighting to front blue (`0000ff`) and rear red (`ff0000`).

## Design

Create an executable Bash script at `~/.local/bin/light_default`. This directory
is already on the user's `PATH`. The script will enable immediate failure with
`set -e` and invoke the repository's `lights` wrapper using its absolute path:

```bash
~/Documents/personal/pc_tweaks/speakers_ligth/lights solid 0000ff --zones primary
~/Documents/personal/pc_tweaks/speakers_ligth/lights solid ff0000 --zones secondary
```

Using the wrapper preserves its USB group-permission handling. Using an absolute
path makes the command independent of the current working directory. If setting
the primary zones fails, the secondary command will not run.

## Verification

Verify that the script passes `bash -n`, is executable, resolves through
`command -v light_default`, and successfully applies both lighting commands.

## Scope

No aliases, shell startup-file edits, CLI changes, or generalized color options
will be added.
