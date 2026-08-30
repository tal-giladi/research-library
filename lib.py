#!/usr/bin/env python3
"""lib - a personal research library kept as markdown files.

Zero dependencies: standard library only, so there is no venv to maintain and
nothing to install. Frontmatter is the database; every index, dashboard and the
HTML viewer is a generated artifact derived from it.

  py lib.py add <url>          fetch metadata, create a library entry
  py lib.py discover           poll arxiv + feeds listed in sources.yml
  py lib.py build              regenerate README / INBOX / indexes / sidebar / viewer
  py lib.py serve              build, then serve the docsify site locally
  py lib.py view               build, then open the offline library.html card view
  py lib.py sync               apply INBOX.md checkboxes back to frontmatter
  py lib.py read <slug>        mark read (also: status / rate / drop)
  py lib.py list               filter the library
  py lib.py show <slug>        print one entry's metadata
  py lib.py retag <topic>      propose a topic for existing papers
  py lib.py doctor             validate the corpus
"""

import argparse
import datetime
import hashlib
import io
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.abspath(__file__))
LIBRARY = os.path.join(ROOT, "library")
INDEXES = os.path.join(ROOT, "indexes")
TOPICS = os.path.join(ROOT, "topics")
SOURCES = os.path.join(ROOT, "sources.yml")
VIEWER = os.path.join(ROOT, "library.html")

STATUSES = ["inbox", "queued", "reading", "read", "archived", "dropped"]
UNREAD = ("inbox", "queued")
TOPIC_PAGE_THRESHOLD = 5

DIGEST_OPEN = "<!-- LIB:DIGEST -->"
DIGEST_CLOSE = "<!-- /LIB:DIGEST -->"
GEN_OPEN = "<!-- LIB:GENERATED -->"
GEN_CLOSE = "<!-- /LIB:GENERATED -->"

UA = "research-library/1.0 (personal use; python-urllib)"


def today():
    return datetime.date.today().isoformat()


def warn(msg):
    sys.stdout.flush()
    print("  ! " + msg, file=sys.stderr)


def die(msg, code=1):
    print("error: " + msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# A deliberately small YAML subset: scalars, inline lists, block lists and (for
# sources.yml) a top-level list of mappings. Anything fancier is a mistake in
# the file rather than a missing feature here.
# ---------------------------------------------------------------------------

def _split_inline(inner):
    parts, buf, quote = [], "", None
    for ch in inner:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch == ",":
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def _scalar(raw):
    raw = raw.strip()
    if raw == "" or raw in ("~", "null"):
        return None
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        return [_scalar(p) for p in _split_inline(inner)] if inner else []
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1].replace('\\"', '"')
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


KEY_RE = re.compile(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$")


def parse_yaml_map(text):
    """Flat mapping: key: scalar | [inline list] | block list."""
    data, key = {}, None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and key is not None:
            if not isinstance(data.get(key), list):
                data[key] = []
            data[key].append(_scalar(stripped[2:]))
            continue
        m = KEY_RE.match(stripped)
        if not m:
            continue
        key, raw = m.group(1), m.group(2)
        data[key] = _scalar(raw) if raw.strip() else None
    return data


def parse_yaml_records(text):
    """Top-level list of mappings, as used by sources.yml.

    Records are told from list items by indentation, not by shape: a bare URL
    such as `- https://example.com/feed` otherwise looks exactly like a
    `key: value` line to a regex.
    """
    records, cur, key = [], None, None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("- ") and indent == 0:
            cur, key = {}, None
            records.append(cur)
            stripped = stripped[2:].strip()
        elif stripped.startswith("- "):
            if cur is not None and key is not None:
                if not isinstance(cur.get(key), list):
                    cur[key] = []
                cur[key].append(_scalar(stripped[2:]))
            continue
        if cur is None:
            continue
        m = KEY_RE.match(stripped)
        if not m:
            continue
        key, raw = m.group(1), m.group(2)
        cur[key] = _scalar(raw) if raw.strip() else None
    return records


def dump_scalar(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(dump_scalar(x) for x in v) + "]"
    s = str(v)
    if s == "" or s != s.strip() or re.search(r"[:#\[\]\",]", s):
        return '"' + s.replace("\\", " ").replace('"', "'") + '"'
    return s


FIELD_ORDER = ["id", "title", "authors", "url", "pdf", "source", "published",
               "added", "topics", "status", "rating", "read_on", "tags"]


def dump_frontmatter(meta):
    keys = [k for k in FIELD_ORDER if k in meta]
    keys += [k for k in sorted(meta) if k not in FIELD_ORDER]
    return "\n".join((k + ": " + dump_scalar(meta[k])).rstrip() for k in keys)


def parse_frontmatter(text):
    text = text.replace("\r\n", "\n")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block = text[text.find("\n") + 1:end]
    rest = text[end + 4:]
    return parse_yaml_map(block), rest.lstrip("\n")


# ---------------------------------------------------------------------------
# paper records
# ---------------------------------------------------------------------------

class Paper:
    def __init__(self, path, meta, body):
        self.path = path
        self.meta = meta
        self.body = body

    @property
    def stem(self):
        return os.path.splitext(os.path.basename(self.path))[0]

    @property
    def relpath(self):
        return os.path.relpath(self.path, ROOT).replace("\\", "/")

    def get(self, k, default=None):
        v = self.meta.get(k, default)
        return default if v is None else v

    @property
    def topics(self):
        t = self.get("topics", [])
        return [x for x in ([t] if isinstance(t, str) else t) if x]

    @property
    def authors(self):
        a = self.get("authors", [])
        return [str(x) for x in ([a] if isinstance(a, str) else a) if x]

    @property
    def status(self):
        return self.get("status", "inbox")

    @property
    def title(self):
        return str(self.get("title", self.stem))

    def digest_text(self):
        i = self.body.find(DIGEST_OPEN)
        j = self.body.find(DIGEST_CLOSE)
        if i == -1 or j == -1:
            return ""
        return self.body[i + len(DIGEST_OPEN):j].strip()

    def is_digested(self):
        d = self.digest_text()
        return bool(d) and "Not digested yet" not in d

    def tldr(self, limit=260):
        d = self.digest_text()
        if not d:
            return ""
        m = re.search(r"###\s*TL;DR\s*\n(.+?)(?=\n#{2,3}\s|\Z)", d, re.S | re.I)
        chunk = m.group(1) if m else d
        # Take the first whole paragraph, not the first line: digests are hard
        # wrapped, so a line-at-a-time reader truncates mid-sentence.
        para = []
        for line in chunk.split("\n"):
            line = line.strip()
            if line.startswith(("#", ">", "<!--", "|", "- ")):
                continue
            if not line:
                if para:
                    break
                continue
            para.append(line)
        text = " ".join(para)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"[*_`]", "", text)
        text = re.sub(r"^(Abstract \(source\):|Not digested yet\.?)\s*", "", text).strip()
        if not text:
            return ""
        return text[:limit] + ("..." if len(text) > limit else "")

    def write(self):
        text = "---\n" + dump_frontmatter(self.meta) + "\n---\n\n" + self.body.lstrip("\n")
        return write_if_changed(self.path, text)


def write_if_changed(path, text):
    text = text.replace("\r\n", "\n")
    if os.path.exists(path):
        with io.open(path, "r", encoding="utf-8") as f:
            if f.read().replace("\r\n", "\n") == text:
                return False
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return True


def read_text(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def load_papers():
    papers = []
    for dirpath, _dirs, files in os.walk(LIBRARY):
        for name in sorted(files):
            if not name.endswith(".md"):
                continue
            path = os.path.join(dirpath, name)
            meta, body = parse_frontmatter(read_text(path))
            if not meta:
                warn("no frontmatter, skipped: " + os.path.relpath(path, ROOT))
                continue
            papers.append(Paper(path, meta, body))
    papers.sort(key=lambda p: (str(p.get("added", "")), p.stem), reverse=True)
    return papers


def resolve(papers, query):
    q = query.strip().lower()
    exact = [p for p in papers
             if p.stem.lower() == q or str(p.get("id", "")).lower() == q]
    if len(exact) == 1:
        return exact[0]
    hits = [p for p in papers if q in p.stem.lower() or q in p.title.lower()
            or q in str(p.get("id", "")).lower()]
    if not hits:
        die("no entry matches '%s'" % query)
    if len(hits) > 1:
        print("ambiguous, %d matches:" % len(hits), file=sys.stderr)
        for p in hits[:12]:
            print("  " + p.stem + "   " + p.title, file=sys.stderr)
        sys.exit(1)
    return hits[0]


def slugify(text, maxlen=60):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    if len(text) > maxlen:
        text = text[:maxlen].rsplit("-", 1)[0]
    return text or "untitled"


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "")
        raw = resp.read(4_000_000)
    charset = "utf-8"
    m = re.search(r"charset=([\w\-]+)", ctype, re.I)
    if m:
        charset = m.group(1)
    return raw.decode(charset, "replace"), ctype


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = a.get("property") or a.get("name")
            val = a.get("content")
            if key and val and key.lower() not in self.meta:
                self.meta[key.lower()] = val

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()


ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+)", re.I)
DOI_RE = re.compile(r"doi\.org/(10\.[^\s?#]+)", re.I)


def arxiv_id_from_url(url):
    m = ARXIV_RE.search(url)
    if not m:
        return None
    ident = m.group(1)
    ident = re.sub(r"\.pdf$", "", ident, flags=re.I)
    ident = re.sub(r"v\d+$", "", ident)
    return ident


ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def _arxiv_entry_to_record(e):
    title = " ".join((e.findtext(ATOM + "title") or "").split())
    summary = " ".join((e.findtext(ATOM + "summary") or "").split())
    ident = (e.findtext(ATOM + "id") or "").strip()
    short = arxiv_id_from_url(ident) or ident
    published = (e.findtext(ATOM + "published") or "")[:10]
    authors = [" ".join((a.findtext(ATOM + "name") or "").split())
               for a in e.findall(ATOM + "author")]
    pdf = ""
    for link in e.findall(ATOM + "link"):
        if link.get("title") == "pdf":
            pdf = link.get("href", "")
    cat = e.find(ARXIV_NS + "primary_category")
    return {
        "id": "arxiv:" + short,
        "title": title,
        "authors": authors,
        "url": "https://arxiv.org/abs/" + short,
        "pdf": pdf,
        "source": "arxiv",
        "published": published,
        "abstract": summary,
        "primary_category": cat.get("term") if cat is not None else "",
    }


_arxiv_last_call = [0.0]
# arXiv asks for one request per three seconds, and its edge throttles bursts
# harder than that with a 429 carrying no Retry-After. Four seconds between
# calls plus a patient backoff is what keeps a multi-topic discover run alive.
ARXIV_MIN_GAP = 4.0
ARXIV_BACKOFF = [15, 30, 60]
ARXIV_SAFE_SCAN = 100  # result windows much beyond this also draw a 429


def arxiv_query(params):
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(params)
    text = None
    for attempt in range(len(ARXIV_BACKOFF) + 1):
        gap = ARXIV_MIN_GAP - (time.monotonic() - _arxiv_last_call[0])
        if gap > 0:
            time.sleep(gap)
        try:
            text, _ = http_get(url, timeout=120)  # cs.CL and friends take ~45s
            break
        except (urllib.error.HTTPError, OSError) as exc:
            # HTTPError is itself an OSError, so test it first: only 429 is
            # worth retrying, while a timeout or reset always is.
            code = getattr(exc, "code", None)
            retryable = (code == 429) if isinstance(exc, urllib.error.HTTPError) else True
            if not retryable or attempt == len(ARXIV_BACKOFF):
                raise
            wait = ARXIV_BACKOFF[attempt]
            warn("arxiv throttled (%s), waiting %ds" % (code or type(exc).__name__, wait))
            time.sleep(wait)
        finally:
            _arxiv_last_call[0] = time.monotonic()
    root = ET.fromstring(text)
    return [_arxiv_entry_to_record(e) for e in root.findall(ATOM + "entry")]


def arxiv_by_id(ident):
    rows = arxiv_query({"id_list": ident, "max_results": 1})
    return rows[0] if rows else None


DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
]


def normalize_date(raw):
    if not raw:
        return ""
    raw = raw.strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    if m:
        return m.group(1)
    cleaned = re.sub(r"\s+GMT$", " +0000", raw)
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


ARXIV_RSS = "https://rss.arxiv.org/rss/"
ANNOUNCE_RE = re.compile(r"^arXiv:\S+\s*Announce Type:\s*\w+\s*(?:Abstract:)?\s*", re.I)


def arxiv_rss(cat):
    """The daily announcement feed: one cheap cached request, versus ~45s and a
    coin-flip 429 for the equivalent sorted API query. Empty at weekends, which
    is what the API fallback in discover is for."""
    text, _ = http_get(ARXIV_RSS + cat, timeout=30)
    items = parse_feed(text)
    for it in items:
        it["source"] = "arxiv"
        it["abstract"] = ANNOUNCE_RE.sub("", it.get("abstract", "")).strip()
    return items


def parse_feed(text):
    """RSS 2.0 or Atom -> list of {title, url, published, abstract, authors}."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        warn("feed is not valid XML: %s" % exc)
        return []
    items = []
    for item in root.iter():
        tag = item.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        def find(*names):
            # `find(a) or find(b)` would be wrong: an ElementTree element with
            # no children is falsy, so every leaf date and summary would fall
            # through to None. Compare against None explicitly.
            for name in names:
                for child in item:
                    if child.tag.split("}")[-1] == name:
                        return child
            return None
        title_el, link_el = find("title"), find("link")
        url = ""
        if link_el is not None:
            url = (link_el.get("href") or link_el.text or "").strip()
        date_el = find("pubDate", "published", "updated", "date")
        desc_el = find("description", "summary", "content")
        desc = ""
        if desc_el is not None and desc_el.text:
            desc = " ".join(re.sub(r"<[^>]+>", " ", unescape(desc_el.text)).split())
        if not url:
            continue
        creator = find("creator")  # dc:creator, which is where arXiv puts authors
        authors = []
        if creator is not None and creator.text:
            authors = [a.strip() for a in re.split(r",| and ", creator.text) if a.strip()]
        items.append({
            "title": " ".join((title_el.text or "").split()) if title_el is not None else url,
            "url": url,
            "published": normalize_date(date_el.text if date_el is not None else ""),
            "abstract": desc[:1200],
            "authors": authors,
        })
    return items


def fetch_metadata(url):
    """Best effort; never fails hard, because losing a pasted link is worse
    than storing one with a thin record."""
    ident = arxiv_id_from_url(url)
    if ident:
        try:
            rec = arxiv_by_id(ident)
            if rec:
                return rec
        except Exception as exc:
            warn("arxiv lookup failed (%s), falling back to page metadata" % exc)
    rec = {
        "id": "", "title": "", "authors": [], "url": url, "pdf": "",
        "source": "manual", "published": "", "abstract": "",
    }
    doi = DOI_RE.search(url)
    if doi:
        rec["id"] = "doi:" + doi.group(1).rstrip("/")
    try:
        text, ctype = http_get(url)
    except Exception as exc:
        warn("could not fetch %s (%s)" % (url, exc))
        rec["title"] = url.rstrip("/").rsplit("/", 1)[-1] or url
        return rec
    if "pdf" in ctype.lower():
        rec["pdf"] = url
        rec["title"] = url.rstrip("/").rsplit("/", 1)[-1].replace(".pdf", "")
        warn("target is a PDF; title guessed from the filename, edit it if wrong")
        return rec
    p = MetaParser()
    try:
        p.feed(text)
    except Exception:
        pass
    meta = p.meta
    rec["title"] = (meta.get("og:title") or meta.get("citation_title")
                    or meta.get("twitter:title") or p.title or url)
    rec["abstract"] = (meta.get("og:description") or meta.get("description")
                       or meta.get("twitter:description") or "")
    author = meta.get("citation_author") or meta.get("author") or meta.get("article:author")
    if author:
        rec["authors"] = [a.strip() for a in re.split(r",| and ", author) if a.strip()]
    rec["published"] = normalize_date(meta.get("citation_publication_date")
                                      or meta.get("article:published_time")
                                      or meta.get("date") or "")
    if meta.get("citation_pdf_url"):
        rec["pdf"] = meta["citation_pdf_url"]
    if meta.get("citation_doi") and not rec["id"]:
        rec["id"] = "doi:" + meta["citation_doi"]
    rec["title"] = " ".join(str(rec["title"]).split())
    rec["abstract"] = " ".join(str(rec["abstract"]).split())[:1500]
    return rec


def canonical_id(rec):
    if rec.get("id"):
        return rec["id"]
    url = rec.get("url", "")
    parts = urllib.parse.urlsplit(url)
    norm = (parts.netloc.lower().replace("www.", "") + parts.path.rstrip("/")).lower()
    return "url:" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# creating entries
# ---------------------------------------------------------------------------

STUB_BODY = """# {title}

{digest_open}
_Not digested yet._ Run `/digest {stem}` in Claude Code, or `py lib.py show {stem}`
to get the link and do it by hand.

**Abstract (source):** {abstract}
{digest_close}

## Notes

"""


def make_entry(rec, topics, status="inbox", added=None):
    added = added or today()
    year = (rec.get("published") or added)[:4] or added[:4]
    stem = added + "-" + slugify(rec.get("title") or rec.get("url", ""))
    path = os.path.join(LIBRARY, year, stem + ".md")
    n = 2
    while os.path.exists(path):
        path = os.path.join(LIBRARY, year, "%s-%d.md" % (stem, n))
        n += 1
    stem = os.path.splitext(os.path.basename(path))[0]
    meta = {
        "id": canonical_id(rec),
        "title": rec.get("title") or rec.get("url"),
        "authors": rec.get("authors") or [],
        "url": rec.get("url", ""),
        "source": rec.get("source", "manual"),
        "published": rec.get("published", ""),
        "added": added,
        "topics": topics or ["unsorted"],
        "status": status,
        "rating": None,
        "read_on": None,
    }
    if rec.get("pdf"):
        meta["pdf"] = rec["pdf"]
    body = STUB_BODY.format(
        title=meta["title"], stem=stem,
        abstract=rec.get("abstract") or "(none captured)",
        digest_open=DIGEST_OPEN, digest_close=DIGEST_CLOSE)
    return Paper(path, meta, body)


def existing_ids(papers):
    return {str(p.get("id", "")): p for p in papers if p.get("id")}


def cmd_add(args):
    papers = load_papers()
    known = existing_ids(papers)
    rec = fetch_metadata(args.url)
    if args.title:
        rec["title"] = args.title
    ident = canonical_id(rec)
    if ident in known and not args.force:
        p = known[ident]
        print("already in the library as %s (%s)" % (p.stem, p.status))
        print("  " + p.relpath)
        return
    topics = [t.strip() for t in (args.topics or "").split(",") if t.strip()]
    paper = make_entry(rec, topics, status=args.status)
    paper.write()
    print("added  %s" % paper.relpath)
    print("       %s" % paper.title)
    print("       id=%s  topics=%s" % (paper.get("id"), ", ".join(paper.topics)))
    if not args.no_build:
        build(quiet=True)


def load_sources():
    if not os.path.exists(SOURCES):
        die("no sources.yml; create one (see README) before running discover")
    return parse_yaml_records(read_text(SOURCES))


def as_list(v):
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


def matches_terms(rec, terms):
    """No terms means the whole category, which is what max_per_run is for."""
    if not terms:
        return True
    hay = (str(rec.get("title", "")) + " " + str(rec.get("abstract", ""))).lower()
    return any(str(t).lower() in hay for t in terms)


def cmd_discover(args):
    papers = load_papers()
    known = existing_ids(papers)
    known_urls = {str(p.get("url", "")).rstrip("/") for p in papers}
    sources = load_sources()
    if args.topic:
        sources = [s for s in sources if s.get("topic") == args.topic]
        if not sources:
            die("no source in sources.yml has topic '%s'" % args.topic)
    cutoff = ""
    days = args.days if args.days is not None else 14
    if days > 0:
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

    # One request per category per run, shared across topics that name it. The
    # filtering happens here rather than in the query because arXiv's API
    # answers 429 to anything with AND or a quoted phrase in it.
    cat_cache = {}

    def scan_category(cat, size):
        return arxiv_query({
            "search_query": "cat:" + cat, "start": 0, "max_results": size,
            "sortBy": "submittedDate", "sortOrder": "descending",
        })

    def category_recent(cat):
        """Today's announcements by RSS; the slow API only when that is empty
        (weekends, holidays) or --backfill asks for a wider window."""
        if cat in cat_cache:
            return cat_cache[cat]
        rows = []
        if not args.backfill:
            try:
                rows = arxiv_rss(cat)
            except Exception as exc:
                warn("arxiv rss for %s failed (%s), falling back to the API" % (cat, exc))
        if not rows:
            if not args.backfill:
                print("        rss empty, querying the api instead")
            try:
                rows = scan_category(cat, args.scan)
            except Exception:
                if args.scan <= ARXIV_SAFE_SCAN:
                    raise
                warn("scan of %d failed, retrying %s at %d"
                     % (args.scan, cat, ARXIV_SAFE_SCAN))
                rows = scan_category(cat, ARXIV_SAFE_SCAN)
        cat_cache[cat] = rows
        return rows

    created, seen_run = 0, set()
    for src in sources:
        topic = src.get("topic") or "unsorted"
        limit = args.limit or src.get("max_per_run") or 10
        terms = as_list(src.get("match"))
        candidates = []
        for cat in as_list(src.get("categories")):
            print("arxiv   [%s] cat:%s" % (topic, cat))
            try:
                rows = category_recent(cat)
            except Exception as exc:
                warn("arxiv category %s failed: %s" % (cat, exc))
                continue
            hits = [r for r in rows if matches_terms(r, terms)]
            print("        %d of %d recent match" % (len(hits), len(rows)))
            candidates += hits
        if src.get("arxiv"):
            # Escape hatch for a hand-written API query. Simple ones work;
            # anything with AND or a quoted phrase tends to come back 429.
            print("arxiv   [%s] %s" % (topic, src["arxiv"]))
            try:
                candidates += arxiv_query({
                    "search_query": src["arxiv"], "start": 0,
                    "max_results": max(limit * 3, 20),
                    "sortBy": "submittedDate", "sortOrder": "descending",
                })
            except Exception as exc:
                warn("arxiv query failed: %s" % exc)
        for feed in as_list(src.get("feeds")):
            print("feed    [%s] %s" % (topic, feed))
            try:
                text, _ = http_get(feed, timeout=30)
                items = [i for i in parse_feed(text) if matches_terms(i, terms)]
                for item in items:
                    item["source"] = "rss"
                candidates += items
            except Exception as exc:
                warn("feed failed (%s): %s" % (feed, exc))

        candidates.sort(key=lambda r: str(r.get("published") or ""), reverse=True)
        taken = 0
        for rec in candidates:
            if taken >= limit:
                break
            ident = canonical_id(rec)
            if ident in known or ident in seen_run:
                continue
            if rec.get("url", "").rstrip("/") in known_urls:
                continue
            seen_run.add(ident)
            if cutoff and rec.get("published") and rec["published"] < cutoff:
                continue
            if args.dry_run:
                print("  + %s  %s" % (rec.get("published", "??????????"), rec.get("title", "")[:90]))
            else:
                paper = make_entry(rec, [topic])
                paper.write()
                known[ident] = paper
                known_urls.add(rec.get("url", "").rstrip("/"))
                print("  + %s" % paper.relpath)
            taken += 1
            created += 1
    print("\n%d new %s" % (created, "candidate" if created == 1 else "candidates")
          + (" (dry run, nothing written)" if args.dry_run else ""))
    if created and not args.dry_run and not args.no_build:
        build(quiet=True)


# ---------------------------------------------------------------------------
# generated views
# ---------------------------------------------------------------------------

def md_escape(text):
    return str(text).replace("|", "\\|").replace("[", "(").replace("]", ")")


def link_to(from_dir, paper):
    rel = os.path.relpath(paper.path, from_dir).replace("\\", "/")
    return rel


def replace_generated(path, generated, header_if_new=""):
    if os.path.exists(path):
        text = read_text(path)
        if GEN_OPEN in text and GEN_CLOSE in text:
            i = text.index(GEN_OPEN) + len(GEN_OPEN)
            j = text.index(GEN_CLOSE)
            new = text[:i] + "\n" + generated + "\n" + text[j:]
            return write_if_changed(path, new)
        new = text.rstrip("\n") + "\n\n" + GEN_OPEN + "\n" + generated + "\n" + GEN_CLOSE + "\n"
        return write_if_changed(path, new)
    new = header_if_new + GEN_OPEN + "\n" + generated + "\n" + GEN_CLOSE + "\n"
    return write_if_changed(path, new)


def row_line(from_dir, p, show_status=True):
    bits = ["[%s](%s)" % (md_escape(p.title), link_to(from_dir, p))]
    if p.topics:
        bits.append("`" + "` `".join(p.topics) + "`")
    if show_status:
        bits.append(p.status)
    if p.get("rating"):
        bits.append("*" * int(p.get("rating")))
    return "- " + "  -  ".join(bits)


def build_inbox(papers):
    unread = [p for p in papers if p.status in UNREAD]
    unread.sort(key=lambda p: (str(p.get("added", "")), str(p.get("published", ""))), reverse=True)
    lines = ["# Inbox", "",
             "%d unread. Tick a box and run `py lib.py sync` to mark it read;"
             " ticking works in the GitHub web UI too." % len(unread), ""]
    if not unread:
        lines.append("_Nothing waiting. Run `py lib.py discover`._")
    for p in unread:
        meta = []
        if p.topics:
            meta.append("`" + "` `".join(p.topics) + "`")
        if p.get("published"):
            meta.append(str(p.get("published")))
        if p.get("url"):
            meta.append("[source](%s)" % p.get("url"))
        if not p.is_digested():
            meta.append("_no digest_")
        lines.append("- [ ] [%s](%s)%s" % (
            md_escape(p.title), link_to(ROOT, p),
            ("  -  " + "  -  ".join(meta)) if meta else ""))
    lines.append("")
    return write_if_changed(os.path.join(ROOT, "INBOX.md"), "\n".join(lines) + "\n")


def build_by_date(papers):
    lines = ["# By date added", ""]
    current = None
    for p in papers:
        year = str(p.get("added", "????"))[:4]
        if year != current:
            current = year
            lines += ["", "## " + year, ""]
        lines.append("- `%s`  %s" % (p.get("added", ""), row_line(INDEXES, p)[2:]))
    return write_if_changed(os.path.join(INDEXES, "by-date.md"), "\n".join(lines) + "\n")


def build_by_topic(papers, counts):
    lines = ["# By topic", ""]
    big = sorted([t for t, n in counts.items() if n >= TOPIC_PAGE_THRESHOLD])
    small = sorted([t for t, n in counts.items() if n < TOPIC_PAGE_THRESHOLD])
    if big:
        lines += ["## Topics with their own page", ""]
        for t in big:
            lines.append("- [%s](../topics/%s.md)  -  %d papers" % (t, t, counts[t]))
        lines.append("")
    if small:
        lines += ["## Tags below the page threshold (%d papers)" % TOPIC_PAGE_THRESHOLD, ""]
        for t in small:
            lines.append("### %s  (%d)" % (t, counts[t]))
            for p in papers:
                if t in p.topics:
                    lines.append(row_line(INDEXES, p))
            lines.append("")
    return write_if_changed(os.path.join(INDEXES, "by-topic.md"), "\n".join(lines) + "\n")


def build_by_author(papers):
    by = {}
    for p in papers:
        for a in p.authors:
            by.setdefault(a, []).append(p)
    lines = ["# By author", "", "%d authors." % len(by), ""]
    for a in sorted(by, key=lambda x: x.split()[-1].lower() if x.split() else x):
        lines.append("### %s  (%d)" % (a, len(by[a])))
        for p in by[a]:
            lines.append(row_line(INDEXES, p))
        lines.append("")
    return write_if_changed(os.path.join(INDEXES, "by-author.md"), "\n".join(lines) + "\n")


def build_by_rating(papers):
    rated = [p for p in papers if p.get("rating")]
    rated.sort(key=lambda p: int(p.get("rating")), reverse=True)
    lines = ["# By rating", "", "%d rated." % len(rated), ""]
    for p in rated:
        lines.append(row_line(INDEXES, p))
    if not rated:
        lines.append("_Nothing rated yet. `py lib.py rate <slug> 4`._")
    return write_if_changed(os.path.join(INDEXES, "by-rating.md"), "\n".join(lines) + "\n")


TOPIC_HEADER = """# {topic}

## Synthesis

_What this topic adds up to. Yours to write - nothing below the line overwrites it._

"""


def build_topic_pages(papers, counts):
    changed, with_pages = 0, []
    for topic, n in sorted(counts.items()):
        path = os.path.join(TOPICS, topic + ".md")
        if n < TOPIC_PAGE_THRESHOLD and not os.path.exists(path):
            continue
        rows = [p for p in papers if topic in p.topics]
        lines = ["## Papers (%d)" % len(rows), ""]
        for p in sorted(rows, key=lambda p: str(p.get("published") or p.get("added")), reverse=True):
            lines.append(row_line(TOPICS, p))
        changed += bool(replace_generated(path, "\n".join(lines),
                                          TOPIC_HEADER.format(topic=topic)))
        with_pages.append(topic)
    return changed, with_pages


def build_sidebar(papers, counts, topic_pages):
    """docsify navigation. Paths are root-relative because index.html aliases
    every /*/_sidebar.md back to this one file."""
    unread = sum(1 for p in papers if p.status in UNREAD)
    lines = ["- [Library](/)",
             "- [Inbox (%d)](INBOX.md)" % unread,
             "",
             "- **Indexes**",
             "  - [By date](indexes/by-date.md)",
             "  - [By topic](indexes/by-topic.md)",
             "  - [By author](indexes/by-author.md)",
             "  - [By rating](indexes/by-rating.md)",
             ""]
    if topic_pages:
        lines.append("- **Topics**")
        for t in topic_pages:
            lines.append("  - [%s (%d)](topics/%s.md)" % (t, counts.get(t, 0), t))
        lines.append("")
    recent = papers[:8]
    if recent:
        lines.append("- **Recently added**")
        for p in recent:
            lines.append("  - [%s](%s)" % (md_escape(p.title), p.relpath))
        lines.append("")
    return write_if_changed(os.path.join(ROOT, "_sidebar.md"), "\n".join(lines))


README_HEADER = """# Research library

Markdown in, markdown out. Every paper is one file whose frontmatter is the only
source of truth; the dashboard below, `INBOX.md`, `indexes/` and `library.html`
are generated from it by `py lib.py build`.

"""


def build_readme(papers, counts):
    by_status = {s: 0 for s in STATUSES}
    for p in papers:
        by_status[p.status] = by_status.get(p.status, 0) + 1
    undigested = [p for p in papers if not p.is_digested()]
    reading = [p for p in papers if p.status == "reading"]
    recent = papers[:10]

    lines = ["## Library", "",
             "**%d papers**  -  %s" % (
                 len(papers),
                 "  ".join("%s %d" % (s, by_status[s]) for s in STATUSES if by_status.get(s))),
             "",
             "[Inbox](INBOX.md) (%d)  -  [by date](indexes/by-date.md)  -  "
             "[by topic](indexes/by-topic.md)  -  [by author](indexes/by-author.md)  -  "
             "[by rating](indexes/by-rating.md)" % sum(by_status.get(s, 0) for s in UNREAD),
             ""]
    if reading:
        lines += ["### Currently reading", ""]
        lines += [row_line(ROOT, p, show_status=False) for p in reading]
        lines.append("")
    lines += ["### Last added", ""]
    for p in recent:
        lines.append("- `%s`  [%s](%s)  -  %s" % (
            p.get("added", ""), md_escape(p.title), link_to(ROOT, p), p.status))
    lines.append("")
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:12]
    if top:
        lines += ["### Topics", "",
                  "  ".join("`%s` %d" % (t, n) for t, n in top), ""]
    if undigested:
        lines += ["### Waiting for a digest (%d)" % len(undigested), ""]
        for p in undigested[:10]:
            lines.append("- [%s](%s)" % (md_escape(p.title), link_to(ROOT, p)))
        if len(undigested) > 10:
            lines.append("- ... and %d more" % (len(undigested) - 10))
        lines.append("")
    lines.append("_Generated by `py lib.py build` on %s._" % today())
    return replace_generated(os.path.join(ROOT, "README.md"), "\n".join(lines), README_HEADER)


def build_viewer(papers):
    data = []
    for p in papers:
        data.append({
            "id": p.get("id", ""), "t": p.title, "a": p.authors, "tp": p.topics,
            "s": p.status, "r": p.get("rating") or 0, "ad": str(p.get("added", "")),
            "pb": str(p.get("published", "")), "u": p.get("url", ""),
            "p": p.relpath, "d": p.tldr(), "dg": p.is_digested(),
        })
    # `\/` is legal JSON, and escaping it stops a title containing "</script>"
    # from closing the data block early.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = VIEWER_TEMPLATE.replace("__DATA__", payload).replace("__BUILT__", today())
    return write_if_changed(VIEWER, page)


def build(quiet=False):
    papers = load_papers()
    counts = {}
    for p in papers:
        for t in p.topics:
            counts[t] = counts.get(t, 0) + 1
    changed = 0
    changed += build_inbox(papers)
    changed += build_by_date(papers)
    changed += build_by_topic(papers, counts)
    changed += build_by_author(papers)
    changed += build_by_rating(papers)
    topic_changes, topic_pages = build_topic_pages(papers, counts)
    changed += topic_changes
    changed += build_sidebar(papers, counts, topic_pages)
    changed += build_readme(papers, counts)
    changed += build_viewer(papers)
    if not quiet:
        print("%d papers, %d topics, %d generated file(s) rewritten"
              % (len(papers), len(counts), changed))
    return papers


def cmd_build(args):
    build()


def cmd_view(args):
    build(quiet=True)
    print("opening " + VIEWER)
    webbrowser.open("file:///" + VIEWER.replace("\\", "/"))


def cmd_serve(args):
    """docsify fetches the markdown over HTTP, so file:// will not do."""
    import functools
    import http.server
    build(quiet=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = "http://127.0.0.1:%d/" % args.port
    print("serving %s at %s  (ctrl-c to stop)" % (ROOT, url))
    if not args.no_open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


# ---------------------------------------------------------------------------
# state changes
# ---------------------------------------------------------------------------

def set_status(paper, status, rating=None):
    paper.meta["status"] = status
    if status == "read" and not paper.meta.get("read_on"):
        paper.meta["read_on"] = today()
    if status in UNREAD:
        paper.meta["read_on"] = None
    if rating is not None:
        paper.meta["rating"] = rating
    paper.write()


def cmd_status(args):
    papers = load_papers()
    p = resolve(papers, args.slug)
    if args.value not in STATUSES:
        die("status must be one of: " + ", ".join(STATUSES))
    set_status(p, args.value)
    print("%s -> %s" % (p.stem, args.value))
    if not args.no_build:
        build(quiet=True)


def cmd_read(args):
    papers = load_papers()
    p = resolve(papers, args.slug)
    set_status(p, "read", rating=args.rating)
    print("read   %s%s" % (p.stem, ("  rating %d" % args.rating) if args.rating else ""))
    if not args.no_build:
        build(quiet=True)


def cmd_rate(args):
    papers = load_papers()
    p = resolve(papers, args.slug)
    if not 1 <= args.rating <= 5:
        die("rating must be 1-5")
    p.meta["rating"] = args.rating
    if p.status in UNREAD:
        p.meta["status"] = "read"
        p.meta["read_on"] = today()
    p.write()
    print("%s rated %d" % (p.stem, args.rating))
    if not args.no_build:
        build(quiet=True)


def cmd_drop(args):
    papers = load_papers()
    p = resolve(papers, args.slug)
    set_status(p, "dropped")
    print("dropped %s (the file stays, so discover will not re-add it)" % p.stem)
    if not args.no_build:
        build(quiet=True)


CHECKED_RE = re.compile(r"^\s*-\s*\[[xX]\]\s*.*?\(([^)]+\.md)\)")


def cmd_sync(args):
    path = os.path.join(ROOT, "INBOX.md")
    if not os.path.exists(path):
        die("no INBOX.md yet; run `py lib.py build`")
    papers = load_papers()
    by_rel = {p.relpath: p for p in papers}
    marked = 0
    for line in read_text(path).split("\n"):
        m = CHECKED_RE.match(line)
        if not m:
            continue
        rel = m.group(1).lstrip("./")
        p = by_rel.get(rel)
        if not p:
            warn("ticked line points at an unknown file: " + rel)
            continue
        if p.status in UNREAD:
            set_status(p, "read")
            print("read   %s" % p.stem)
            marked += 1
    print("%d marked read" % marked)
    build(quiet=True)


# ---------------------------------------------------------------------------
# querying
# ---------------------------------------------------------------------------

def cmd_list(args):
    papers = load_papers()
    if args.status:
        papers = [p for p in papers if p.status == args.status]
    if args.topic:
        papers = [p for p in papers if args.topic in p.topics]
    if args.undigested:
        papers = [p for p in papers if not p.is_digested()]
    if args.match:
        q = args.match.lower()
        papers = [p for p in papers
                  if q in p.title.lower() or q in " ".join(p.authors).lower()
                  or q in p.body.lower()]
    for p in papers[:args.limit]:
        print("%-10s %-9s %s" % (p.get("added", ""), p.status, p.title[:80]))
        print("           %s" % p.stem)
    print("\n%d shown" % min(len(papers), args.limit))


def cmd_show(args):
    papers = load_papers()
    p = resolve(papers, args.slug)
    if args.json:
        out = dict(p.meta)
        out["path"] = p.relpath
        out["stem"] = p.stem
        out["digested"] = p.is_digested()
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    print("path      " + p.relpath)
    print("stem      " + p.stem)
    for k in FIELD_ORDER:
        if p.meta.get(k) not in (None, "", []):
            print("%-10s%s" % (k, dump_scalar(p.meta[k])))
    print("digested  " + ("yes" if p.is_digested() else "no"))


def cmd_retag(args):
    papers = load_papers()
    terms = [t.strip().lower() for t in args.match.split(",") if t.strip()]
    if not terms:
        die("give at least one --match term")
    hits = []
    for p in papers:
        if args.topic in p.topics:
            continue
        hay = (p.title + " " + " ".join(p.authors) + " " + p.body).lower()
        if any(t in hay for t in terms):
            hits.append(p)
    for p in hits:
        print("%s  %s" % ("APPLY" if args.apply else "     ", p.title[:80]))
        if args.apply:
            p.meta["topics"] = sorted(set(p.topics + [args.topic]))
            p.write()
    print("\n%d %s" % (len(hits), "retagged" if args.apply else "candidates (re-run with --apply)"))
    if args.apply:
        build(quiet=True)


def cmd_doctor(args):
    papers = load_papers()
    problems = 0
    seen = {}
    for p in papers:
        ident = str(p.get("id", ""))
        if not ident:
            print("no id:        " + p.relpath)
            problems += 1
        elif ident in seen:
            print("duplicate id: %s\n              %s\n              %s"
                  % (ident, seen[ident], p.relpath))
            problems += 1
        else:
            seen[ident] = p.relpath
        if p.status not in STATUSES:
            print("bad status:   %s (%s)" % (p.relpath, p.status))
            problems += 1
        if not p.get("url"):
            print("no url:       " + p.relpath)
            problems += 1
        if not p.get("title"):
            print("no title:     " + p.relpath)
            problems += 1
        if DIGEST_OPEN not in p.body or DIGEST_CLOSE not in p.body:
            print("no digest markers: " + p.relpath)
            problems += 1
        r = p.get("rating")
        if r is not None and (not isinstance(r, int) or not 1 <= r <= 5):
            print("bad rating:   %s (%r)" % (p.relpath, r))
            problems += 1
    undigested = sum(1 for p in papers if not p.is_digested())
    print("\n%d papers, %d undigested, %d problem(s)" % (len(papers), undigested, problems))
    sys.exit(1 if problems else 0)


# ---------------------------------------------------------------------------

VIEWER_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Research library</title>
<style>
  :root {
    --bg: #fbfaf8; --panel: #ffffff; --ink: #1c1a17; --muted: #6b6660;
    --line: #e5e0d8; --accent: #7a4b2a; --chip: #f0ebe3; --shadow: 0 1px 2px rgba(0,0,0,.06);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #16151a; --panel: #1e1d23; --ink: #eceaf0; --muted: #9b96a3;
      --line: #302e38; --accent: #d0a17a; --chip: #2a2831; --shadow: none;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 15px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; }
  header { position: sticky; top: 0; z-index: 5; background: var(--bg);
           border-bottom: 1px solid var(--line); padding: 14px 20px 10px; }
  h1 { margin: 0 0 10px; font-size: 17px; letter-spacing: .01em; font-weight: 650; }
  h1 span { color: var(--muted); font-weight: 400; }
  input[type=search] { width: 100%; padding: 9px 12px; font-size: 15px; color: var(--ink);
    background: var(--panel); border: 1px solid var(--line); border-radius: 7px; outline: none; }
  input[type=search]:focus { border-color: var(--accent); }
  .filters { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
  .chip { font: inherit; font-size: 12.5px; padding: 3px 10px; border-radius: 999px; cursor: pointer;
    background: var(--chip); color: var(--muted); border: 1px solid transparent; }
  .chip.on { background: var(--accent); color: var(--bg); border-color: var(--accent); }
  main { padding: 16px 20px 60px; max-width: 980px; margin: 0 auto; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 9px;
    padding: 12px 14px; margin-bottom: 9px; box-shadow: var(--shadow); }
  .card h2 { margin: 0 0 5px; font-size: 15.5px; font-weight: 600; line-height: 1.35; }
  .card h2 a { color: var(--ink); text-decoration: none; }
  .card h2 a:hover { color: var(--accent); }
  .meta { color: var(--muted); font-size: 12.5px; display: flex; flex-wrap: wrap; gap: 5px 10px; }
  .tldr { margin: 7px 0 0; color: var(--ink); opacity: .9; font-size: 14px; }
  .tag { background: var(--chip); border-radius: 4px; padding: 1px 6px; cursor: pointer; }
  .st { text-transform: uppercase; letter-spacing: .05em; font-size: 11px; font-weight: 600; }
  .st-inbox, .st-queued { color: var(--accent); }
  .nodigest { color: var(--muted); font-style: italic; }
  .empty { color: var(--muted); padding: 40px 0; text-align: center; }
  footer { color: var(--muted); font-size: 12px; text-align: center; padding: 0 0 30px; }
  a { color: var(--accent); }
</style>
</head>
<body>
<header>
  <h1>Research library <span id="count"></span></h1>
  <input type="search" id="q" placeholder="Search title, author, topic, summary&hellip;  (press /)" autocomplete="off">
  <div class="filters" id="statusFilters"></div>
  <div class="filters" id="topicFilters"></div>
</header>
<main id="list"></main>
<footer>Generated __BUILT__ &middot; read-only view of the markdown files &middot; mark things read with <code>py lib.py read &lt;slug&gt;</code></footer>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const STATUSES = ['inbox','queued','reading','read','archived','dropped'];
let q = '', status = '', topic = '';

const topics = {};
DATA.forEach(p => (p.tp || []).forEach(t => topics[t] = (topics[t] || 0) + 1));
const topTopics = Object.keys(topics).sort((a, b) => topics[b] - topics[a]).slice(0, 24);

function chip(label, active, onClick) {
  const b = document.createElement('button');
  b.className = 'chip' + (active ? ' on' : '');
  b.textContent = label;
  b.onclick = onClick;
  return b;
}

function renderFilters() {
  const sf = document.getElementById('statusFilters');
  sf.innerHTML = '';
  sf.appendChild(chip('all', status === '', () => { status = ''; render(); }));
  STATUSES.forEach(s => {
    const n = DATA.filter(p => p.s === s).length;
    if (!n) return;
    sf.appendChild(chip(s + ' ' + n, status === s, () => { status = status === s ? '' : s; render(); }));
  });
  const tf = document.getElementById('topicFilters');
  tf.innerHTML = '';
  topTopics.forEach(t => tf.appendChild(
    chip(t + ' ' + topics[t], topic === t, () => { topic = topic === t ? '' : t; render(); })));
}

function match(p) {
  if (status && p.s !== status) return false;
  if (topic && !(p.tp || []).includes(topic)) return false;
  if (!q) return true;
  const hay = [p.t, (p.a || []).join(' '), (p.tp || []).join(' '), p.d, p.id].join(' ').toLowerCase();
  return q.split(/\s+/).every(term => hay.includes(term));
}

function render() {
  renderFilters();
  const rows = DATA.filter(match);
  document.getElementById('count').textContent =
    rows.length + ' of ' + DATA.length;
  const list = document.getElementById('list');
  list.innerHTML = '';
  if (!rows.length) {
    list.innerHTML = '<p class="empty">Nothing matches.</p>';
    return;
  }
  rows.forEach(p => {
    const card = document.createElement('div');
    card.className = 'card';
    const h = document.createElement('h2');
    const a = document.createElement('a');
    a.href = p.p; a.textContent = p.t;
    h.appendChild(a);
    card.appendChild(h);

    const meta = document.createElement('div');
    meta.className = 'meta';
    const st = document.createElement('span');
    st.className = 'st st-' + p.s; st.textContent = p.s;
    meta.appendChild(st);
    if (p.r) { const r = document.createElement('span'); r.textContent = '★'.repeat(p.r); meta.appendChild(r); }
    if (p.a && p.a.length) {
      const au = document.createElement('span');
      au.textContent = p.a.slice(0, 3).join(', ') + (p.a.length > 3 ? ' et al.' : '');
      meta.appendChild(au);
    }
    if (p.pb || p.ad) {
      const d = document.createElement('span');
      d.textContent = p.pb ? 'published ' + p.pb : 'added ' + p.ad;
      meta.appendChild(d);
    }
    (p.tp || []).forEach(t => {
      const tag = document.createElement('span');
      tag.className = 'tag'; tag.textContent = t;
      tag.onclick = () => { topic = topic === t ? '' : t; render(); };
      meta.appendChild(tag);
    });
    if (p.u) {
      const src = document.createElement('a');
      src.href = p.u; src.target = '_blank'; src.rel = 'noopener'; src.textContent = 'source';
      meta.appendChild(src);
    }
    card.appendChild(meta);

    const tl = document.createElement('p');
    tl.className = 'tldr' + (p.dg ? '' : ' nodigest');
    tl.textContent = p.d || 'No digest yet.';
    card.appendChild(tl);
    list.appendChild(card);
  });
}

document.getElementById('q').addEventListener('input', e => {
  q = e.target.value.trim().toLowerCase();
  render();
});
document.addEventListener('keydown', e => {
  if (e.key === '/' && document.activeElement.id !== 'q') {
    e.preventDefault();
    document.getElementById('q').focus();
  }
});
render();
</script>
</body>
</html>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lib", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def nb(p):
        p.add_argument("--no-build", action="store_true",
                       help="skip regenerating the indexes afterwards")
        return p

    a = sub.add_parser("add", help="add one paper by URL")
    a.add_argument("url")
    a.add_argument("--topics", help="comma separated")
    a.add_argument("--title", help="override the fetched title")
    a.add_argument("--status", default="inbox", choices=STATUSES)
    a.add_argument("--force", action="store_true", help="add even if the id already exists")
    nb(a).set_defaults(func=cmd_add)

    d = sub.add_parser("discover", help="poll sources.yml for new candidates")
    d.add_argument("--topic", help="only this topic")
    d.add_argument("--limit", type=int, help="max new entries per source")
    d.add_argument("--days", type=int, help="ignore items older than N days (0 = no limit)")
    d.add_argument("--scan", type=int, default=ARXIV_SAFE_SCAN,
                   help="recent papers pulled per arXiv category (default %d; larger "
                        "windows are often refused and fall back to it)" % ARXIV_SAFE_SCAN)
    d.add_argument("--backfill", action="store_true",
                   help="skip the daily RSS and query the API for a wider window "
                        "(slow, use after a gap)")
    d.add_argument("--dry-run", action="store_true")
    nb(d).set_defaults(func=cmd_discover)

    sub.add_parser("build", help="regenerate every derived file").set_defaults(func=cmd_build)
    sub.add_parser("view", help="build, then open the offline library.html card view"
                   ).set_defaults(func=cmd_view)

    sv = sub.add_parser("serve", help="build, then serve the docsify site locally")
    sv.add_argument("--port", type=int, default=8899)
    sv.add_argument("--no-open", action="store_true")
    sv.set_defaults(func=cmd_serve)
    sub.add_parser("sync", help="apply INBOX.md checkboxes").set_defaults(func=cmd_sync)

    r = sub.add_parser("read", help="mark as read")
    r.add_argument("slug")
    r.add_argument("--rating", type=int)
    nb(r).set_defaults(func=cmd_read)

    s = sub.add_parser("status", help="set any status")
    s.add_argument("slug")
    s.add_argument("value", choices=STATUSES)
    nb(s).set_defaults(func=cmd_status)

    rt = sub.add_parser("rate", help="rate 1-5 (implies read)")
    rt.add_argument("slug")
    rt.add_argument("rating", type=int)
    nb(rt).set_defaults(func=cmd_rate)

    dr = sub.add_parser("drop", help="not interested; keeps the stub so it stays deduped")
    dr.add_argument("slug")
    nb(dr).set_defaults(func=cmd_drop)

    ls = sub.add_parser("list", help="filter the library")
    ls.add_argument("--status", choices=STATUSES)
    ls.add_argument("--topic")
    ls.add_argument("--match", help="substring of title, authors or body")
    ls.add_argument("--undigested", action="store_true")
    ls.add_argument("--limit", type=int, default=50)
    ls.set_defaults(func=cmd_list)

    sh = sub.add_parser("show", help="print one entry")
    sh.add_argument("slug")
    sh.add_argument("--json", action="store_true")
    sh.set_defaults(func=cmd_show)

    rg = sub.add_parser("retag", help="propose a topic for existing papers")
    rg.add_argument("topic")
    rg.add_argument("--match", required=True, help="comma separated search terms")
    rg.add_argument("--apply", action="store_true")
    rg.set_defaults(func=cmd_retag)

    sub.add_parser("doctor", help="validate the corpus").set_defaults(func=cmd_doctor)

    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)  # readable when piped to a log
    except (AttributeError, ValueError):
        pass
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
