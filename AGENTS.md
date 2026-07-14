# Agent guide

To control the Logitech G560 speaker lighting, use the `./lights` wrapper at the
repo root, e.g.:

```bash
./lights solid 0000ff --zones primary      # front zones -> blue
./lights solid ff0000 --zones secondary    # rear zones  -> red
./lights off                               # all zones off
./lights list-zones                        # commands, zones, aliases
```

The full reference — commands, zones, colors, the `sg` USB-permission handling,
setup, and troubleshooting — is in [CLAUDE.md](./CLAUDE.md). Read that before
making changes.
