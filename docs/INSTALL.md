# Install — distill

## Requirements

- **macOS** for the included launchd plists; **Linux** works with cron (see Linux section)
- **Python 3.11+** (`python3 --version`)
- **[Claude Code CLI](https://docs.claude.com/claude-code)** installed and authenticated (`claude --print "hello"` must work)
- A real or empty **Obsidian vault** to use as `BRAIN_ROOT`
- **`gh` CLI** (optional, only needed for `weekly-drafts.sh` — the capture-candidate flow)

## Install (macOS)

### 1. Clone

```bash
git clone https://github.com/evgeniynezivoy/distill ~/distill
cd ~/distill
```

### 2. Verify the engine

```bash
pytest .bin/tests/ -v
```

Expected: `24 passed`. If anything fails, the engine isn't ready — file an issue.

### 3. Bootstrap your vault

If you already have an Obsidian vault you want to use:

```bash
export BRAIN_ROOT=~/your-vault-path
mkdir -p "$BRAIN_ROOT/_meta/drafts/lessons" "$BRAIN_ROOT/logs/daily" "$BRAIN_ROOT/logs/weekly"
mkdir -p "$BRAIN_ROOT/projects" "$BRAIN_ROOT/lessons"

# If your vault doesn't have these files yet
cp examples/sample-vault/INDEX.md           "$BRAIN_ROOT/" 2>/dev/null
cp examples/sample-vault/_meta/PROJECTS.tsv "$BRAIN_ROOT/_meta/" 2>/dev/null
```

If you're starting fresh:
```bash
export BRAIN_ROOT=~/brain
mkdir -p "$BRAIN_ROOT"
cp -r examples/sample-vault/. "$BRAIN_ROOT/"
```

### 4. Configure your projects

Edit `$BRAIN_ROOT/_meta/PROJECTS.tsv` — one line per git repo you want tracked:

```
# path	tier	nick
/Users/you/code/my-app	hot	my-app
/Users/you/code/my-lib	warm	my-lib
```

For each `nick`, create a project note at `$BRAIN_ROOT/projects/<nick>.md`. You can copy `examples/sample-vault/projects/my-app.md` as a template.

### 5. Populate frontmatter from real git state

```bash
BRAIN_ROOT="$BRAIN_ROOT" python3 .bin/harvest.py
```

`harvest.py` walks each repo in `PROJECTS.tsv`, fetches the latest origin state, and writes frontmatter (`last_commit_date`, `current_branch`, `behind`, etc.) into your project notes. It's idempotent — safe to re-run any time. Without this step, your `projects/<nick>.md` files keep the sample dates and the synthesis sees zero active projects.

### 6. First manual prompt build (no API call yet)

```bash
python3 .bin/build_daily_prompt.py --brain-root "$BRAIN_ROOT" --today $(date +%Y-%m-%d)
```

Read-only — builds the prompt and prints it to stdout. Verify your active projects, lessons, and history blocks render correctly.

### 7. First real run (API call)

```bash
bash .bin/daily.sh
```

Cost: ~$0.05-0.10 on Sonnet 4.6 for a small vault.

Inspect outputs:
```bash
cat $BRAIN_ROOT/logs/daily/$(date +%Y-%m-%d).md
ls  $BRAIN_ROOT/_meta/drafts/lessons/
```

Compare project notes — only `## Daily synthesis (auto)` should change; your curated sections should be byte-equal.

### 8. Schedule via launchd

```bash
# Copy plist templates
cp examples/launchd/com.example.distill.daily.plist  ~/Library/LaunchAgents/com.YOURUSERNAME.distill.daily.plist
cp examples/launchd/com.example.distill.weekly.plist ~/Library/LaunchAgents/com.YOURUSERNAME.distill.weekly.plist

# Open each in your editor and replace:
#   YOUR_USERNAME → your actual macOS username
#   BRAIN_ROOT path → your actual vault path
#   Label "com.example.distill.*" → "com.YOURUSERNAME.distill.*"

# Validate
plutil -lint ~/Library/LaunchAgents/com.YOURUSERNAME.distill.daily.plist
plutil -lint ~/Library/LaunchAgents/com.YOURUSERNAME.distill.weekly.plist

# Load
launchctl load ~/Library/LaunchAgents/com.YOURUSERNAME.distill.daily.plist
launchctl load ~/Library/LaunchAgents/com.YOURUSERNAME.distill.weekly.plist

# Confirm
launchctl list | grep distill
```

The daemon runs daily at 09:00, weekly Sunday 18:00. Edit `StartCalendarInterval` in the plist to change.

## Install (Linux)

Same as macOS through step 6. For scheduling, use cron:

```bash
crontab -e
```

Add:
```
# distill daily synthesis @ 09:00
0 9 * * * BRAIN_ROOT=/home/you/brain /home/you/distill/.bin/daily.sh

# distill weekly synthesis @ Sun 18:00
0 18 * * 0 BRAIN_ROOT=/home/you/brain /home/you/distill/.bin/weekly.sh
```

Linux push notifications: replace the `osascript` call in `daily.sh:notify()` with `notify-send`:
```bash
notify() {
  command -v notify-send >/dev/null && notify-send "distill" "$1"
}
```

## Troubleshooting

### `claude --print` returns "Cannot be launched inside another Claude Code session"

The synthesis script needs to unset `CLAUDECODE` / `CLAUDE_CODE_SIMPLE`. The provided scripts already do this. If you're testing manually from a Claude Code shell, run:
```bash
unset CLAUDECODE CLAUDE_CODE_SIMPLE
```

### "ERROR: claude output missing ---START-DAILY-LOG--- marker"

Claude returned malformed output. The raw response is saved to `$BRAIN_ROOT/.bin/logs/daily-YYYY-MM-DD.raw` for inspection. Usually: prompt was too long, hit a token cap, or the model invented a different format. Check the raw log.

### Tests pass but daemon never runs

Check `launchctl list | grep distill`. Status `-` means loaded-but-never-ran; that's normal until the scheduled time. If you don't see your label at all — `launchctl load` failed silently. Check:
```bash
launchctl print gui/$(id -u)/com.YOURUSERNAME.distill.daily
```

### Daily run consumes too many tokens / costs more than expected

Default model is `claude-sonnet-4-6` (~$0.05/day on a small vault). If your vault has 30+ lessons, the prompt grows linearly. Options:
- Switch to a smaller fixture set of "core" lessons
- Move stale lessons to a `lessons/_archive/` subfolder (the engine globs only `lessons/*.md`)
- See `ARCHITECTURE.md` § "30+ lessons" for the eventual refactor

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.YOURUSERNAME.distill.daily.plist
launchctl unload ~/Library/LaunchAgents/com.YOURUSERNAME.distill.weekly.plist
rm ~/Library/LaunchAgents/com.YOURUSERNAME.distill.*.plist
rm -rf ~/distill
```

Your vault (`BRAIN_ROOT`) is untouched.
