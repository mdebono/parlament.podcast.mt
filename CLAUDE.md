# Il-Podcast tal-Parlament (parlament.podcast.mt)

An unofficial podcast of Malta's Parliament's sittings, built nightly from parlament.mt by `python -m parlament` (`.github/workflows/pages.yml`). Decisions are in `docs/decisions.md`.

## Rules
- **Branches:** always `claude/` followed by a name saying what the change is, in lower-case words joined by hyphens (e.g. `claude/parlament-fetch-worker`, `claude/feed-new-url`); never a session id or a random suffix. One branch per change; a follow-up to a merged branch gets a new name.
- **Log every decision** in `docs/decisions.md` as the next D-number, and update the docs it affects in the same change.
- **Public repo:** keep docs, comments and commit messages short and about how things work now; no history of earlier approaches, account or security settings, or test runs.
- **parlament.mt:** requests go through the fetch Worker (`fetch/`, `PARLAMENT_VIA`) with our own user-agent.

## Running
- `pip install -r requirements.txt`; tests: `python -m unittest discover -s parlament/tests`.
- parlament.mt and R2 are unreachable from a Claude Code session; the `verify` skill (`.claude/skills/verify/SKILL.md`) fakes both.
