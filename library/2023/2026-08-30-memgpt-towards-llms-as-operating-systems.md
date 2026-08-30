---
id: "arxiv:2310.08560"
title: "MemGPT: Towards LLMs as Operating Systems"
authors: [Charles Packer, Sarah Wooders, Kevin Lin, Vivian Fang, Shishir G. Patil, Ion Stoica, Joseph E. Gonzalez]
url: "https://arxiv.org/abs/2310.08560"
pdf: "https://arxiv.org/pdf/2310.08560v2"
source: arxiv
published: 2023-10-12
added: 2026-08-30
topics: [agent-memory, agent-harness]
status: read
rating: 5
read_on: 2026-08-30
---

# MemGPT: Towards LLMs as Operating Systems

<!-- LIB:DIGEST -->
### TL;DR
MemGPT treats the context window as RAM and everything else as disk, and makes the
model itself responsible for paging between them via function calls. A queue manager
warns the model at 70% capacity and flushes with recursive summarisation at 100%, so
an agent can hold a conversation or a document far larger than its window.

### Why it matters
This is the paper that reframed agent memory as an operating-systems problem rather
than a retrieval-tuning problem, and the distinction is load-bearing: the agent decides
what to page in, so the policy is inspectable and promptable instead of buried in a
similarity threshold. Everything since that talks about "memory tiers" or "self-editing
memory" is arguing with this design.

### Key claims
- A hierarchy of main context (RAM) and external context (disk) gives the appearance of
  unbounded context without a longer window.
- The LLM should drive its own paging through function calls rather than have retrieval
  applied to it by the harness.
- Function chaining via a `request_heartbeat` flag lets the model make several retrieval
  calls inside one inference cycle, which is what makes multi-hop lookups possible.

### Method
Main context = system instructions + a fixed working-context block + a FIFO message
queue; external context = archival storage (read/write, long text) and recall storage
(message history). Evaluated on a Multi-Session Chat dataset (deep memory retrieval and
conversation openers) and on document analysis: NaturalQuestions-Open document QA over
Wikipedia, and a synthetic nested key-value retrieval task. Baselines are GPT-3.5 Turbo,
GPT-4 and GPT-4 Turbo with ordinary lossy summarisation.

### Numbers
Deep memory retrieval accuracy: GPT-4 Turbo 35.3% baseline → 93.4% with MemGPT; GPT-4
32.1% → 92.5%; GPT-3.5 Turbo 38.7% → 66.9%. On nested key-value retrieval the GPT-4
baselines collapse to 0% at three or more levels of nesting while MemGPT holds across
all levels. Conversation-opener similarity to human openers: 0.868 against a human
baseline around 0.8. Document QA accuracy stays flat as the document count grows, where
the fixed-context baselines degrade.

### Limitations
The authors note MemGPT often stops paging through retriever results before exhausting
the database, so document QA is under-answered rather than wrong. GPT-3.5's much weaker
result is the tell: the whole design is a function-calling harness, so it inherits the
underlying model's tool-use competence and degrades with it. The DMR baselines are also
unflatteringly simple — lossy summarisation, not a tuned retrieval pipeline — so the
headline deltas measure "paging beats truncation", not "MemGPT beats good RAG".

### Related
- [Lost in the Middle](https://arxiv.org/abs/2307.03172) - why a longer window is not
  the same as more usable recall, and the reason paging pays off.
- [Generative Agents](https://arxiv.org/abs/2304.03442) - the other 2023 answer to the
  same question, scoring memories by recency/importance/relevance instead of paging.
<!-- /LIB:DIGEST -->

## Notes

