# Optional: the draw.io desktop CLI

devant draws self-contained `.drawio` XML with **no tools required**. If the user has installed the
draw.io **desktop CLI**, this skill uses it for one thing by default: **ELK auto-layout** (so you
don't hand-tune coordinates) — it rewrites the same `.drawio`. Image export (PNG/SVG/PDF) is
supported but **off by default**; devant's deliverable is the `.drawio` file, which the user reads
and edits themselves. The CLI is **optional** and the plugin never installs or requires it.

> Adapted from the official draw.io Claude Code skill (jgraph/drawio-mcp, Apache-2.0) and the
> Agents365-ai/drawio-skill (MIT). devant uses only the CLI, no MCP.

## Detect the CLI (do this first, remember the exact command)

Try these in order; the first that prints a version is your binary — use that exact command in every
later call. **Prefer the `drawio` binary on PATH** (the canonical name for Homebrew, the `.deb`/
`.rpm` packages, and native WSL installs); only fall back to a platform-specific path if PATH has no
`drawio`.

```bash
# 1) canonical — the drawio binary on PATH (Linux, macOS, native WSL .deb install)
drawio --version || draw.io --version

# 2) WSL2 ONLY IF draw.io is installed on Windows instead of inside the distro — the /mnt/c exe
grep -qi microsoft /proc/version 2>/dev/null && "/mnt/c/Program Files/draw.io/draw.io.exe" --version

# 3) other fallbacks
/Applications/draw.io.app/Contents/MacOS/draw.io --version     # macOS .app, no Homebrew wrapper
"C:\Program Files\draw.io\draw.io.exe" --version               # Windows native
```

Double-quote paths with spaces; never wrap a path in backticks (that would execute it). If none
print a version, the CLI is absent — skip layout and deliver the hand-authored `.drawio`.

**Headless note (native Linux / WSL):** `--version` runs bare, but any *rendering* call (`--layout`,
export) launches Electron and needs a display — prefix those with `xvfb-run -a`
(e.g. `xvfb-run -a drawio -x -f xml --layout verticalFlow -o d.drawio d.drawio`). Install once with
`sudo apt install -y xvfb`.

## Install it (WSL2 — user runs these, not devant)

On WSL2 the simplest route is to install **draw.io Desktop on Windows** and call it from WSL via
`/mnt/c` — no Linux GUI/xvfb needed:

1. Download the Windows installer from https://github.com/jgraph/drawio-desktop/releases (the
   `*-windows-installer.exe`) and install it on Windows.
2. From WSL, verify: `"/mnt/c/Program Files/draw.io/draw.io.exe" --version`.
3. (Optional) add a shell alias so commands below can say `drawio`:
   `alias drawio='"/mnt/c/Program Files/draw.io/draw.io.exe"'`

Alternative — install natively **inside** WSL (headless needs a virtual display):
```bash
# download the .deb from the releases page, then:
sudo apt install ./drawio-amd64-*.deb
sudo apt install -y xvfb            # headless display for CLI export
xvfb-run -a drawio --version
```
Prefer the Windows-exe route on WSL2; the native route pulls in Electron + xvfb.

Suggest these to the user with `! <command>` so the login/install runs in their own shell — devant
does not install software.

## ELK auto-layout (let the CLI place nodes)

Author the styled cells with approximate coordinates, then let ELK arrange them — the same layouts
as the editor's *Arrange ▸ Layout* menu. Your styles are preserved; only positions change.

```bash
# lay out in place (read + overwrite the same file is supported)
drawio -x -f xml --layout verticalFlow -o diagram.drawio diagram.drawio
```

| Preset | Layout | Use for |
|---|---|---|
| `verticalFlow` | layered, top→bottom | activity flows, pipelines |
| `horizontalFlow` | layered, left→right | request/response chains |
| `verticalTree` / `horizontalTree` | tree | hierarchies, org/context |
| `radialTree` | radial | hub-and-spoke |
| `organic` | force-directed | networks / many-edge architecture |

Match the preset to devant's flow direction: activity → `verticalFlow`; layered architecture →
`horizontalFlow` or `verticalTree`.

## Export to an image (OFF by default — only when the user explicitly asks)

devant's deliverable is the `.drawio` file. Only run an export if the user asks for a PNG/SVG/PDF.

```bash
drawio -x -f png -e -b 10 -o diagram.drawio.png diagram.drawio     # png | svg | pdf
```
- `-e` embeds the diagram XML so the exported file reopens as an editable diagram — use the double
  extension `name.drawio.png` to signal that.
- Do **not** export a Mermaid `.mmd` straight to PNG with `-e` (broken in current Desktop) — always
  produce the `.drawio` first, then export it.
- Known issue: `-e` PNG output can have a truncated final chunk; if a strict PNG reader rejects it,
  re-export as SVG or without `-e`.

## Opening the result (only if the user asks)

Don't auto-open a viewer — the user reads/edits the `.drawio` themselves and says when to continue.
If they ask to open it (WSL2):

```bash
cmd.exe /c start "" "$(wslpath -w diagram.drawio)"      # or an exported .png/.svg/.pdf
```
The empty `""` after `start` is required (it's the window-title slot). Otherwise just print the
absolute path.
