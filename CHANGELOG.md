# Changelog

## 0.4.0

### Added
- temporal occurrence fields on `KnowledgeRecord` plus time-scoped retrieval in `DomainMemoryEngine`
- explicit provenance-backed observation synthesis via `synthesize_observation()`
- namespace retrieval policies with confidence floors, source allowlists, hop defaults, and rerank controls
- opt-in second-stage reranking with a default deterministic `TokenOverlapReranker`
- self-contained test support via local `mocker` fixture fallback

### Changed
- hybrid scoring now includes a temporal signal when a query or record carries time information
- SQLite and Postgres adapters persist occurrence windows
- pytest path configuration now works from a plain repository checkout

## 0.3.0

### Added
- in-memory hybrid retrieval engine
- Postgres + pgvector canonical store
- Kuzu projection worker and queue controls
- staged/canonical/pattern memory tiers
- bootstrap, demo, doctor, projector, and project-memory CLIs
- verified package install path and source-first runtime path
- examples, getting-started guide, CI workflow, and release-facing docs
- projector replay controls and health checks
