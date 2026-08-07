# `light_default` Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install a globally available `light_default` command that restores the Logitech G560 front zones to blue and rear zones to red.

**Architecture:** Add one executable Bash script to the user's existing `~/.local/bin`, which is already on `PATH`. The script delegates both operations to the repository's absolute `lights` wrapper path so it retains USB permission handling and works from every current directory.

**Tech Stack:** Bash, the repository `lights` wrapper, standard shell verification commands

## Global Constraints

- The command name is exactly `light_default`.
- Primary zones use `0000ff`; secondary zones use `ff0000`.
- Stop immediately if the primary-zone command fails.
- Do not edit shell startup files or the lighting CLI.

---

### Task 1: Install and verify the command

**Files:**
- Create: `~/.local/bin/light_default`
- Test: shell assertions and the physical G560 device

**Interfaces:**
- Consumes: `~/Documents/personal/pc_tweaks/speakers_ligth/lights <command>`
- Produces: executable command `light_default` with no arguments and exit status from the delegated lighting operations

- [x] **Step 1: Run the installation assertions before creating the command**

```bash
test -f ~/.local/bin/light_default \
  && test -x ~/.local/bin/light_default \
  && bash -n ~/.local/bin/light_default \
  && test "$(command -v light_default)" = ~/.local/bin/light_default
```

Expected: FAIL because `~/.local/bin/light_default` does not exist.

- [x] **Step 2: Create the minimal executable**

```bash
#!/usr/bin/env bash
set -e

~/Documents/personal/pc_tweaks/speakers_ligth/lights solid 0000ff --zones primary
~/Documents/personal/pc_tweaks/speakers_ligth/lights solid ff0000 --zones secondary
```

Set mode `0755` on `~/.local/bin/light_default`.

- [x] **Step 3: Run the installation assertions again**

Run the exact assertion chain from Step 1.

Expected: PASS with exit status 0.

- [x] **Step 4: Run from an unrelated directory**

```bash
cd /tmp
light_default
```

Expected: both lighting commands complete successfully; the front zones are blue and rear zones are red.

- [x] **Step 5: Inspect repository state**

```bash
git status --short
```

Expected: the home-directory executable is not added to the repository; only previously existing unrelated user changes, if any, are shown.
