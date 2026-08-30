# Research library

Markdown in, markdown out. Every paper is one file whose YAML frontmatter is the
**only** source of truth. The dashboard below, `INBOX.md`, everything in
`indexes/` and `topics/`, and `library.html` are all generated from those files
by `py lib.py build` — delete any of them and nothing is lost.

No database, no server, no API key, and no dependencies beyond the Python
standard library, so there is no venv to maintain and nothing to install.
Discovery and digesting both run locally; GitHub only ever stores the result.

## Setup

Python 3.10+ and git. That is the whole list.

```bash
git clone <this repo>
cd research-library
py lib.py build
```

Windows PowerShell can use `.\lib.ps1 <command>`, Git Bash `./lib <command>`;
both just call `lib.py`.

## Daily use

```bash
py lib.py discover              # poll sources.yml, write new stubs into the inbox
py lib.py discover --dry-run    # see what it would add first
py lib.py add <url>             # paste a link: fetches metadata, files it
py lib.py serve                 # build + serve the docsify site at :8899
py lib.py read <slug>           # mark read   (also: status / rate / drop)
py lib.py sync                  # apply INBOX.md checkboxes back to frontmatter
py lib.py list --undigested     # what still needs reading properly
py lib.py doctor                # duplicate ids, bad statuses, missing fields
```

Digesting is a Claude Code skill rather than a `lib` command, because that is
the one step that needs a model: `/digest <slug or url>` reads the source and
writes the digest into the file. `lib` never calls a model, which is why it has
no keys and no cost.

## Navigating

Four layers, in the order you will actually reach for them:

| Layer | Good for | Cost |
|---|---|---|
| the docsify site (`py lib.py serve`) | reading digests properly, full-text search, sidebar nav — same setup as the course repos | `index.html` + generated `_sidebar.md`, needs HTTP |
| `INBOX.md`, `indexes/`, `topics/` | reading on GitHub itself, no clone needed | committed markdown |
| `library.html` (`py lib.py view`) | faceted filter by status and topic, TL;DR cards, works offline with no server | generated, gitignored |
| `rg "term" library/` | finding an exact phrase across every digest and note | free |

The docsify layer is the same pattern as `ai-engineer-course`: `index.html` loading
docsify from a CDN, `.nojekyll` so Pages does not hide `_sidebar.md`, and a
`_sidebar.md` that `build` regenerates. It renders the markdown directly rather
than duplicating it, strips the YAML frontmatter and puts status, rating, topics
and source links back as a one-line header.

**Publishing it.** If the repo is public, turn on Pages (Settings → Pages →
branch `main`, folder `/`) and it serves at
`https://tal-giladi.github.io/research-library/`. GitHub Pages will not serve a
private repo on a free plan, so a private library stays on `serve` locally plus
GitHub's own markdown rendering — which is enough for everything except reading
on your phone.

Nothing is ever one giant list: the inbox holds unread only, `by-date` is
sectioned per year, and a topic gets its own page once it reaches five papers
(below that it stays a plain tag under *Tags below the page threshold* in
`indexes/by-topic.md`).

## Read / unread

`status:` in frontmatter is authoritative — `inbox → queued → reading → read`,
plus `archived` and `dropped`. Change it three ways, whichever is nearest:

1. `py lib.py read <slug>` / `rate <slug> 4` / `status <slug> reading`
2. Tick the checkbox in `INBOX.md` **in your editor**, then `py lib.py sync`
3. Edit the file. It is just a file.

Note that checkboxes are not clickable on github.com or on the Pages site:
GitHub renders task lists in repo *files* with `disabled`, and only makes them
interactive inside issues, PRs and comments. From a phone the options are to
edit `INBOX.md` through GitHub's web editor and sync later, or just read there
and mark things read next time you are at the machine.

`git log --follow library/2026/<file>.md` is your reading history, for free.

## Adding a topic

Add a record to [`sources.yml`](sources.yml) and run `discover`. Nothing else —
no schema change, no migration. Existing papers can be back-tagged in one pass:

```bash
py lib.py retag agent-memory --match "memory,context window,retrieval"
py lib.py retag agent-memory --match "memory,context window,retrieval" --apply
```

`dropped` entries keep their stub file on purpose: that is what stops `discover`
from offering the same paper again next week.

## File layout

```
library/<year>/<added>-<slug>.md   the corpus - the only thing that matters
sources.yml                        what discover polls
lib.py                             the whole tool, stdlib only
INBOX.md  indexes/  topics/        generated markdown (committed)
_sidebar.md                        generated docsify nav (committed)
index.html  .nojekyll              the docsify site
library.html                       generated offline viewer (gitignored)
docs/SCHEMA.md                     the frontmatter contract
.claude/skills/digest/             the /digest skill
```

See [docs/SCHEMA.md](docs/SCHEMA.md) for the frontmatter fields and the two
hand-edit rules that keep regeneration safe.

<!-- LIB:GENERATED -->
## Library

**7 papers**  -  inbox 4  reading 1  read 2

[Inbox](INBOX.md) (4)  -  [by date](indexes/by-date.md)  -  [by topic](indexes/by-topic.md)  -  [by author](indexes/by-author.md)  -  [by rating](indexes/by-rating.md)

### Currently reading

- [Introducing Hy4 Preview](library/2026/2026-08-30-introducing-hy4-preview.md)  -  `engineering-blogs`

### Last added

- `2026-08-30`  [Qwen3.8-Flash-Next](library/2026/2026-08-30-qwen3-8-flash-next.md)  -  inbox
- `2026-08-30`  [Quoting Paul Dix](library/2026/2026-08-30-quoting-paul-dix.md)  -  read
- `2026-08-30`  [MemGPT: Towards LLMs as Operating Systems](library/2023/2026-08-30-memgpt-towards-llms-as-operating-systems.md)  -  read
- `2026-08-30`  [Making Large Language Models work for you](library/2026/2026-08-30-making-large-language-models-work-for-you.md)  -  inbox
- `2026-08-30`  [Just a rumour of a bug is enough to find a security exploit these days](library/2026/2026-08-30-just-a-rumour-of-a-bug-is-enough-to-find-a-security-exploit.md)  -  inbox
- `2026-08-30`  [Introducing Hy4 Preview](library/2026/2026-08-30-introducing-hy4-preview.md)  -  reading
- `2026-08-30`  [Breaking Claude Code Opus 5 Auto Mode](library/2026/2026-08-30-breaking-claude-code-opus-5-auto-mode.md)  -  inbox

### Topics

`engineering-blogs` 5  `agent-memory` 1  `agent-harness` 1  `llm-engineering` 1

### Waiting for a digest (6)

- [Qwen3.8-Flash-Next](library/2026/2026-08-30-qwen3-8-flash-next.md)
- [Quoting Paul Dix](library/2026/2026-08-30-quoting-paul-dix.md)
- [Making Large Language Models work for you](library/2026/2026-08-30-making-large-language-models-work-for-you.md)
- [Just a rumour of a bug is enough to find a security exploit these days](library/2026/2026-08-30-just-a-rumour-of-a-bug-is-enough-to-find-a-security-exploit.md)
- [Introducing Hy4 Preview](library/2026/2026-08-30-introducing-hy4-preview.md)
- [Breaking Claude Code Opus 5 Auto Mode](library/2026/2026-08-30-breaking-claude-code-opus-5-auto-mode.md)

_Generated by `py lib.py build` on 2026-08-30._
<!-- /LIB:GENERATED -->
