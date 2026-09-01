---
id: arxiv:2608.30387
title: "Attesting Outputs and Delegation Ancestry in Multi-Agent AI Systems"
authors: [Liu L., Yu H.]
url: https://arxiv.org/abs/2608.30387
pdf: https://arxiv.org/pdf/2608.30387
source: arxiv
published: 2026-08-28
added: 2026-09-01
topics: [llm-security, agent-harness]
status: inbox
rating:
read_on:
---

# Attesting Outputs and Delegation Ancestry in Multi-Agent AI Systems

## Notes

Post-incident evidence for multi-agent systems: which deployer released these bytes, and was each cross-deployer edge authorized? Two layers — deployer runtime signs a hash of released output (records bytes; does not prevent prompt injection) plus ancestry evidence for edge authorization. Compares signed linked list, Merkle-chain, and co-signed DAG; after child-key compromise only the co-signed DAG rejects an unauthorized parent claim. Validated locally and across three AWS AZs; not a prompt-injection defense.
