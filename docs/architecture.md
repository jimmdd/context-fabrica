# context-fabrica Architecture

## Goal

Provide a generic memory method for domain-specific agents that must reason over:
- semantic similarity (what text is relevant), and
- relation topology (how engineering concepts connect).

## Core Method

The MVP uses a **hybrid retrieval pipeline**:
1. **Semantic retrieval** via lexical BM25-like scoring (`LexicalSemanticIndex`).
2. **Graph retrieval** via multi-hop entity relation traversal (`KnowledgeGraph`).
3. **Policy ranking** to combine semantic + graph + recency + confidence.

Final score:

`score = 0.50 * semantic + 0.30 * graph + 0.12 * recency + 0.08 * confidence`

These weights are defaults and intentionally simple for portability.

Alternative production rankers (planned):

- Weighted RRF style fusion:
  `S(d)=sum(w_m/(k+rank_m(d))) + wt*recency + wc*confidence`
- Calibrated additive fusion:
  `p(d)=sigmoid(b0 + bv*vec + bl*lex + bg*graph + bt*recency + bc*confidence)`

## Data Model

- `KnowledgeRecord`: memory unit (text, source, domain, confidence, tags, metadata, timestamp)
- `Relation`: directed typed edge (`source_entity`, `relation`, `target_entity`, `weight`)

## Ingestion Flow

1. Insert/Update record in semantic index.
2. Extract entities from text (capitalized tokens, snake_case, numeric/technical tokens).
3. Extract weak relations from co-occurrence and cues (`depends_on`, `uses`, `implements`, `owns`).
4. Attach entities to record and add graph edges.
5. Persist validity window (`valid_from`, optional `valid_to`) for future as-of queries.

## Query Flow

1. Score prompt against semantic index.
2. Extract query entities and traverse graph up to `hops`.
3. Normalize semantic/graph scores.
4. Add recency/confidence priors.
5. Filter invalid/superseded memories for current-time queries.
6. Return top-k records with rationale tags.

## Service-Oriented Blueprint (for OSS evolution)

- `ingest-service`: append records, normalize metadata, emit extraction jobs
- `extract-service`: entities, relations, contradiction candidates
- `retrieval-service`: lexical/vector retrieval + graph expansion + fusion
- `policy-service`: trust thresholds, source allowlists, conflict policy
- `memory-api`: write/query/invalidate/as-of query endpoints

This package currently implements the core logic in-process to stay lightweight, but interfaces are shaped to split into services later.

## Why This Method Generalizes

- Works without a specific vector DB or graph DB.
- Can be upgraded to embeddings and persistent graph backends with no API changes.
- Separation of concerns allows environment-specific storage adapters.

## Extension Points

- Replace lexical index with embedding store (FAISS/LanceDB/pgvector).
- Replace in-memory graph with Neo4j, Memgraph, or NetworkX-backed persistence.
- Add source verification and conflict detection for trust calibration.
- Add memory lifecycle policies (decay, consolidation, archival).

## References

- GraphRAG architecture: `https://microsoft.github.io/graphrag/index/architecture/`
- Graphiti repository: `https://github.com/getzep/graphiti`
- Neo4j GraphRAG hybrid retriever: `https://github.com/neo4j/neo4j-graphrag-python`
- Mem0 graph memory patterns: `https://github.com/mem0ai/mem0`
- Elasticsearch RRF docs: `https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion`
