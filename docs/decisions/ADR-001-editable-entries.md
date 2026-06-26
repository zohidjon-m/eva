# ADR-001: Editable Past Journal Entries Without Breaking the L0→L4 Recompute

**Status:** Proposed
**Date:** 2026-06-26
**Deciders:** Project owner
**Context docs:** [EVA_MEMORY_ARCHITECTURE.md](../system/EVA_MEMORY_ARCHITECTURE.md), [EVA_SYSTEM_DESIGN.md](../system/EVA_SYSTEM_DESIGN.md)

## Context

The requirement: **any past entry must be editable, and the system must stay correct afterward.** Threat model is benign — edits are typos and rewording, not adversarial — so the design problem is purely **propagation correctness**, not abuse prevention.

The propagation splits cleanly into two halves, and conflating them is what makes this look hard:

| Layer | Nature | Recompute on edit |
|-------|--------|-------------------|
| **L1** (episode record) | Pure function of one entry's text | Re-extract that entry. Already **idempotent** (`db.py` `save_extraction` clears sub-rows) |
| **L2** (embeddings) | Pure function of L1 | Re-embed that entry. Already **upsert by id** |
| **L4** (analytics) | Pure function of L1/L3 | **Computed on demand already** — nothing stored to fix (Memory Architecture §1, L4) |
| **L3** (user model) | **Stateful, incremental, path-dependent** — confidence/decay accumulated over time | **The actual problem** |

So "recompute L0→L4" is mostly **already solved** — three of the four layers are deterministic, per-entry, idempotent caches of L0. The entire difficulty is **L3**, because it was built by replaying operations with decay over time and is *not* a pure function of any single entry.

Two latent issues surface the moment edits are allowed, and both must be fixed regardless of which option is chosen:

1. **No stable entry identity.** L0 blocks are addressed only by `## HH:MM:SS · type` (`vault.py`); the L1 `entries.id` is **autoincrement and reassigned on every full rebuild** (`scripts/reextract.py`). Evidence pointers (§5.1 — *no pointer, no claim*) therefore silently break across any rebuild *today*. Editing just makes this visible. **This is an existing bug.**
2. **Destructive L0 rewrite risks the one irreplaceable store.** `append_entry` cannot corrupt prior data; a block rewrite rewrites the whole day-file.

## Decision

Adopt a **revision-based, append-only L0 with content-hash dirty-tracking and two-speed recompute** — the edit rides the *same* read-loop/write-loop split the architecture already has.

### 1. L0 stays append-only — edits are *revisions*, not rewrites
An edit does not overwrite the block; it appends a **new revision that supersedes the prior one under the same stable `uid`**. The "current text" of an entry is its latest revision. This is the keystone:

- **"Never rewritten" stays literally true** — no data is ever lost; the recovery posture (System Design §recovery) is intact.
- **Feature 8 (time-travel / "how naive I was") survives** — original and edited versions both exist; the past self can still be shown.
- The recompute problem collapses to a clean statement: *"a uid's current content changed."*

Storage: keep prior versions in a sibling `journal/.history/` (or a superseded-revision block). Append-only storage, **editable presentation**.

### 2. Stable `uid` per entry, written into L0
Give every block a content-independent id in its header (e.g. `## 14:03:27 · journal · a1b2c3`). Derived layers key off `uid`, **not** autoincrement rowid. This fixes the latent evidence-pointer bug *and* is the precondition for any targeted recompute.

### 3. Content-hash dirty-tracking → per-entry idempotent recompute (synchronous, cheap)
Each derived row stores the **hash of the L0 text it was computed from**. On edit:
- Hash changes → entry is **dirty** → re-extract **just that entry** (1 model call) → re-embed (upsert) → L4 needs nothing (computed on demand).
- This is the synchronous fast path: **what the user sees is immediately correct**, cost = one extraction + one embedding.
- Bonus: full rebuild becomes **incremental** — only re-extract entries whose hash changed.

### 4. L3 self-heals via evidence pointers on its normal cadence (asynchronous)
Do **not** surgically reverse L3 ops, and do **not** full-rebuild L3 on a typo. Instead:
- On edit of entry X, mark every L3 claim whose evidence pointers include X as `needs_revalidation`.
- The **next nightly/weekly consolidation** re-pulls those claims' (now-updated) cited entries and runs the **cheap verification pass that already exists** (§5.7 — *"is this supported by its cited evidence? yes/no"*). Claims that lost support **decay or drop** via machinery already in the design (§5.4); claims still supported stay. User anchors (`source: user`) are never touched.

L3 is **already eventually-consistent** (it updates nightly, not per-turn). An edit just feeds the existing write loop a "dirty entry" signal. No new invertible-op engine, no replay.

## Options Considered

### Option A — Editable window, freeze after consolidation
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low |
| Correctness | High |
| Meets requirement | **No** |

**Rejected:** explicitly fails the requirement that *past* entries be editable.

### Option B — Full synchronous rebuild from L0 on every edit
| Dimension | Assessment |
|-----------|------------|
| Complexity | Low (reuses `reextract.py`) |
| Cost | **Very high** — replays entire history through a 2B model |
| Correctness | High, but **non-deterministic churn** |

**Pros:** dead simple; matches documented recovery path.
**Cons:** a typo fix triggers thousands of model calls (minutes–hours); worse, re-running L3 from scratch can **silently change unrelated claims** ("I fixed a typo and Eva forgot a pattern"). Unacceptable UX and unbounded cost.

### Option C — Event-sourced invertible L3 op ledger (surgical reversal)
| Dimension | Assessment |
|-----------|------------|
| Complexity | **High** |
| Cost | Low per edit |
| Correctness | High *if* ops are truly invertible |

**Pros:** precise, minimal blast radius.
**Cons:** decay and contradiction-resolution make op effects **state-dependent**, so true inversion is fragile. Turns the already-"hardest single component" (§6) into something harder. Over-engineering for a benign-edit threat model.

### Option D — Revisions + content-hash + two-speed recompute *(recommended, chosen)*
| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium |
| Cost per edit | **One extraction + one embedding** (sync); L3 on existing cadence |
| Correctness | L0/L1/L2/L4 immediate; L3 eventually-consistent (as it already is) |
| Team familiarity | High — reuses idempotent re-extract, upsert, verification pass, decay |

## Trade-off Analysis

The decisive insight: **the system is already ~75% built for this.** L1/L2/L4 are deterministic idempotent caches; the verification pass, decay, and evidence pointers L3 needs already exist in the design. Options B and C both try to make L3 *instantly* consistent after an edit — but L3 is **never** instantly consistent (it is a nightly artifact), so paying for instant consistency solves a problem that does not exist. Option D matches the recompute grain to L3's existing cadence and keeps the synchronous cost bounded to a single entry.

The one real cost of D: **for a few hours after editing a deep-history entry, an L3 claim may cite slightly-stale evidence.** Given the benign threat model and that L3 is already a day stale by design, this is the correct thing to trade away.

## Consequences

**Easier**
- Editing any past entry: bounded, synchronous, one model call.
- Evidence pointers finally stable across rebuilds (latent bug fixed).
- Full rebuild becomes incremental (hash-gated) — faster recovery too.
- Deletion is the same machinery (edit-to-tombstone → dirty → cascade drop → claims revalidate).

**Harder / new work**
- L0 gains a `uid` + revision/history concept and an **atomic rewrite** (temp-file + rename under `_WRITE_LOCK`).
- Derived rows gain a `source_hash` column; a `mark_dirty` / `recompute_entry(uid)` path beside the existing whole-DB `reextract.py`.
- L3 claims gain a `needs_revalidation` flag and a revalidation step in nightly consolidation.

**To revisit**
- If users ever edit deep history *frequently*, consider a small synchronous L3 revalidation for directly-cited claims (a bounded slice of Option C) rather than waiting for nightly.

## Action Items

1. [ ] **Fix the latent identity bug first** — add stable `uid` to L0 blocks; make L1/L2/L3 key off `uid`, not autoincrement rowid (do this even before edit ships).
2. [ ] `vault.py`: `update_entry(uid, new_text)` as an **append-revision + atomic rewrite**; keep prior versions in `journal/.history/`.
3. [ ] Add `source_hash` to `extractions` / L2 rows; `recompute_entry(uid)` doing re-extract → re-embed (reuse idempotent `save_extraction`).
4. [ ] L3: add `needs_revalidation`; on edit mark dependent claims; add a revalidation step to nightly consolidation using the existing §5.7 verification + §5.4 decay.
5. [ ] `PUT /entries/{uid}` endpoint; Phase 11/15 UI: edit affordance on journal history + "show original" for time-travel.
6. [ ] Amend `EVA_MEMORY_ARCHITECTURE.md` §L0 and `EVA_SYSTEM_DESIGN.md` recovery section: "append-only" → "append-only storage with editable presentation via revisions."
7. [ ] Tests: atomic rewrite isolation, hash-gated incremental rebuild, evidence-pointer survival across rebuild, claim revalidation after edit.

---

**Mental model:** L0 append-only revisions are the truth; L1/L2/L4 are a deterministic cache refreshed per-dirty-entry; L3 is an eventually-consistent projection that self-heals through evidence pointers on the cadence it already runs. An edit is just a dirty signal into the write loop.
