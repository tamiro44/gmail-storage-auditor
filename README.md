# Gmail Storage Auditor

A reusable, safety-first Gmail storage optimization skill/agent.

## Goal

Find storage-saving opportunities in Gmail while minimizing deletion regret. The system identifies large and old messages, duplicate attachments, forwarded/self-sent copies, low-value archives, and other cleanup candidates, then ranks them by expected space savings, confidence, and risk.

## Core principles

- Analyze first; never delete during analysis.
- Require explicit user approval before moving any message to Trash.
- Protect sensitive categories by default: tax, legal, financial, medical, identity, employment, and signed documents.
- Treat sentimental media as review-only by default.
- Prefer deterministic duplicate evidence such as same filename + exact byte size + retained authoritative copy.
- Use synthetic fixtures for tests and examples. Never commit real mailbox content.

## Output tiers

- 🟢 Safe candidate — strong duplicate/redundancy evidence and low regret risk.
- 🟡 Review — likely removable, but context or value is uncertain.
- 🟠 Aggressive — meaningful space recovery with higher regret risk.
- 🔴 Keep — sensitive, authoritative, unique, or high-value content.

## Cleanup value

Conceptually:

`Cleanup Value = Space Saved × Confidence ÷ Risk`

The exact scoring model is configurable and should remain explainable.

## Repository structure

- `SKILL.md` — reusable agent/skill workflow
- `AGENTS.md` — agent roles, coordination, and engineering rules
- `config/policy.yaml` — default safety and scoring policy
- `docs/architecture.md` — system design
- `docs/safety.md` — safety gates and approval model
- `docs/agent-board.md` — board/workflow conventions

## Status

v0.1 scaffold. Implementation tasks are tracked as GitHub Issues.
