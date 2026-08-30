---
name: digest
description: Read a paper or article and write its digest into the research library. Use when the user says "/digest", "digest this", pastes a paper/article URL to be added to the library, or asks to summarise something already in the library (by slug, title or arXiv id). Also use when the user asks what still needs digesting and then wants it done.
---

# Digest a library entry

The library lives in this repo. `lib.py` never calls a model; this skill is the
one step that does. Everything else — fetching metadata, indexes, statuses — is
`py lib.py`'s job, so do not hand-write frontmatter or hand-edit the indexes.

## 1. Resolve the target

**Given a URL:** check whether it is already in the library, and add it if not.

```bash
py lib.py add <url> --topics <comma,separated>
```

`add` prints the path, or says `already in the library as <slug>` and exits
without touching anything. Either way you now have a slug.

**Given a slug, title fragment or arXiv id:** go straight to

```bash
py lib.py show <query> --json
```

That returns `path`, `url`, `pdf`, `title`, `topics`, `status` and `digested`.
If it prints `ambiguous`, show the candidates and ask which one. If `digested`
is already `true`, say so and ask before overwriting — the digest block is
replaced wholesale.

## 2. Read the source

Fetch the `url`. For arXiv, the `abs` page gives you the abstract; when you need
the full text prefer `https://ar5iv.labs.arxiv.org/html/<id>` (HTML, readable)
over the PDF. If every fetch fails, say so and stop — do not write a digest from
the title alone, and do not invent numbers or citations.

Read for what the paper actually claims and what it actually measured. A digest
that restates the abstract in different words is worth nothing.

## 3. Write the digest

Edit the file at `path`. Replace **everything between** `<!-- LIB:DIGEST -->`
and `<!-- /LIB:DIGEST -->`, leaving both marker lines in place. Never touch
anything below `## Notes` — that is the user's, and it survives re-digesting.

Use exactly these sections:

```markdown
### TL;DR
Three sentences, no more. The first sentence is what appears in the viewer and
in every generated index, so it has to carry the finding on its own.

### Why it matters
Two or three sentences on what changes if this is true. Connect it to the other
topics in this library where there is a real connection — cross-link with a
relative path like `../2026/2026-08-12-some-paper.md`.

### Key claims
- One bullet per claim, stated as the authors state it.

### Method
What they actually did: datasets, models, scale, how it was evaluated.

### Numbers
The results that matter, with the baseline they are measured against. Say
"not reported" rather than guessing.

### Limitations
What the paper does not establish, plus your own reservations, marked as yours.

### Related
Links to the works it builds on or contradicts.
```

Keep it to roughly 250-450 words. Prose in full sentences; bullets only under
**Key claims** and **Related**.

## 4. Finish

If the entry's topics are still `[unsorted]`, set real ones with the Edit tool
(frontmatter `topics:` is an inline list), preferring topics that already exist
in `sources.yml` or `topics/` over inventing a new one.

Leave `status` alone unless the user asked for a change — digesting is not
reading. Then:

```bash
py lib.py build
```

Report back in two lines: the TL;DR, and the path. Do not paste the whole digest
into the chat — it is in the file.
