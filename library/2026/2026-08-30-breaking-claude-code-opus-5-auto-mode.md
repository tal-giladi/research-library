---
id: "url:ad8111a7bebf"
title: Breaking Claude Code Opus 5 Auto Mode
authors: []
url: "https://simonwillison.net/2026/Aug/27/breaking-claude-code-opus-5-auto-mode/"
source: rss
published: 2026-08-27
added: 2026-08-30
topics: [engineering-blogs]
status: inbox
rating:
read_on:
---

# Breaking Claude Code Opus 5 Auto Mode

<!-- LIB:DIGEST -->
_Not digested yet._ Run `/digest 2026-08-30-breaking-claude-code-opus-5-auto-mode` in Claude Code, or `py lib.py show 2026-08-30-breaking-claude-code-opus-5-auto-mode`
to get the link and do it by hand.

**Abstract (source):** Breaking Claude Code Opus 5 Auto Mode Anthropic are putting a great deal of faith in Claude Code's auto mode for protecting their coding agent users against prompt injection attacks. They recently made that the default and have made bold claims about its effectiveness. Johann Rehberger is one of the most credible prompt injection researchers active today. He found an attack against auto mode which he claims works 80% of the time, by tricking Claude Code into downloading and uncompressing a zip archive, then executing code that imports base64 without noticing that this will import and execute a local struct.py file extracted from the archive. In a few cases auto mode directly prevented the agent from preventing harmful code from continuing to execute! In a few runs Claude tried to terminate the malware process once it noticed the compromise, but Auto Mode denied the cleanup command. Claude detects the compromise, but Auto Mode blocks its cleanup command The safety mechanism itself can become part of the failure. The classifier allowed the creation of the malware process, but then it blocked the command intended to stop it! I agree with Johann's conclusion here: the only safe way to 
<!-- /LIB:DIGEST -->

## Notes

