# The frontmatter contract

One paper, one file, at `library/<year>/<added-date>-<slug>.md`. The year comes
from the publication date when it is known and the date added otherwise; it
exists only so a directory listing stays under GitHub's 1000-file truncation
limit. Nothing reads it, so moving a file between year folders is harmless.

## Fields

```yaml
---
id: arxiv:2310.08560              # natural key - dedupe happens on this alone
title: "MemGPT: Towards LLMs as Operating Systems"
authors: [Packer C., Wooders S.]
url: https://arxiv.org/abs/2310.08560
pdf: https://arxiv.org/pdf/2310.08560     # optional
source: arxiv                     # arxiv | rss | manual
published: 2023-10-12             # from the source; may be empty
added: 2026-08-30                 # when it entered the library
topics: [agent-memory, context-management]
status: inbox                     # see below
rating:                           # 1-5, empty until you rate it
read_on:                          # set automatically when status becomes read
---
```

`id` is `arxiv:<id>` (version stripped), `doi:<doi>`, or `url:<sha1 of the
normalised URL>` as a last resort. Two entries with the same `id` is the one
thing `doctor` treats as corruption.

## Statuses

| status | meaning |
|---|---|
| `inbox` | discovered, not triaged |
| `queued` | you decided to read it |
| `reading` | in progress; shows on the README dashboard |
| `read` | done; `read_on` is stamped |
| `archived` | read and filed away |
| `dropped` | not interested — **keep the file**, it is what stops `discover` re-adding it |

`inbox` and `queued` are what `INBOX.md` lists.

## The two hand-edit rules

**1. Never write inside the digest markers by hand.**

```markdown
<!-- LIB:DIGEST -->
... written by /digest, replaced wholesale on re-digest ...
<!-- /LIB:DIGEST -->

## Notes
Everything from here down is yours and is never touched.
```

**2. Never edit between `<!-- LIB:GENERATED -->` markers.** They appear in
`README.md` and every `topics/*.md` page; `build` replaces that span and leaves
the rest alone. On a topic page the `## Synthesis` section sits *outside* the
markers precisely so it survives.

Fully generated files — `INBOX.md` and everything in `indexes/` — have no
markers because they are rewritten whole. The one exception is ticking an
`INBOX.md` checkbox, which is input: `py lib.py sync` reads those ticks, writes
`status: read` into the real files, and regenerates the inbox without them.

## Digest structure

`/digest` writes these sections, in this order, inside the digest markers:

```markdown
### TL;DR
Three sentences. The first one is what shows up in the viewer and the indexes.

### Why it matters
### Key claims
### Method
### Numbers
### Limitations
### Related
```

The TL;DR extraction is deliberate: `lib.py` pulls the first prose line under
`### TL;DR` for every generated summary, so that line is the one that has to
earn its place.

## The YAML subset

`lib.py` ships its own ~60-line parser rather than depending on PyYAML, so it
understands a restricted grammar: scalars, `[inline, lists]`, block lists, and
(in `sources.yml` only) a top-level list of mappings distinguished by
indentation. Strings containing `:`, `,`, `[`, `]`, `"` or `#` are quoted on
write. Anything more exotic is a mistake in the file rather than a feature
request. `py lib.py doctor` catches the damage.
