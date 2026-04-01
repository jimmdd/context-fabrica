# Backend Decision Matrix

Engineering guide for choosing vector store and graph store backends for `context-fabrica`.

---

## Vector Store Comparison

### Decision Axes

| Backend | Deployment | Filtering | Hybrid Search | Persistence | Licensing | Best Scale Range |
|---------|-----------|-----------|---------------|-------------|-----------|-----------------|
| **In-memory (BM25)** | Embedded | N/A | Lexical only | None (ephemeral) | MIT (ours) | <100K records |
| **FAISS** | Embedded lib | Manual post-filter | No native | Manual save/load | MIT | 100K–10M vectors |
| **LanceDB** | Embedded file | Native column filters | FTS + vector | Columnar files | Apache-2.0 | 100K–5M vectors |
| **pgvector** | Postgres extension | Full SQL WHERE | FTS + vector via pg | Full ACID | PostgreSQL License | 100K–50M vectors |
| **Qdrant** | Standalone service | Payload filters | Native hybrid (RRF) | Disk + WAL | Apache-2.0 | 1M–1B vectors |
| **Weaviate** | Standalone service | Schema-based | Native hybrid | Disk persistence | BSD-3 | 1M–1B vectors |
| **Milvus** | Distributed cluster | Attribute filters | Sparse + dense | Distributed | Apache-2.0 | 10M–10B vectors |

### Benchmark Summary (Q1 2026, 1M vectors, 1536 dimensions)

Sources: Salt Technologies AI Vector DB Benchmark 2026, MariaDB Big Vector Search Benchmark (March 2026)

| Backend | p50 Latency | p99 Latency | QPS @94% Recall | Memory (1M vecs) | Cold Start |
|---------|-------------|-------------|-----------------|-------------------|------------|
| **FAISS (CPU)** | 0.5ms | — | 15K | 3.1GB | N/A (lib) |
| **FAISS (GPU)** | 0.08ms | — | 50K+ | 2-3GB | N/A (lib) |
| **LanceDB** | ~10-15ms | ~50-70ms | — | Low (mmap) | N/A (embedded) |
| **pgvector** | 18ms | 90ms | 250 | Postgres heap | N/A (extension) |
| **Qdrant** | 4ms | 25ms | 90-150 | 6GB | Fast |
| **Weaviate** | 12ms | 65ms | 470-570 | Moderate | Moderate |
| **Milvus** | 6ms | 35ms | 90-150 | Distributed | Slow |

### Filtering Performance Impact

| Backend | No Filter | Simple Equality | Boolean (AND/OR) | Range + Equality |
|---------|-----------|-----------------|-------------------|------------------|
| **FAISS** | 0.5ms | +2-10ms (manual post-filter) | Manual | Manual |
| **pgvector** | 18ms | +5-20ms (SQL WHERE) | Full SQL | Full SQL |
| **Qdrant** | 4ms | +6ms | +11ms | +6-8ms |
| **Weaviate** | 12ms | +5-10ms | Schema-based | Schema-based |

### Detailed Profiles

#### FAISS (facebook/faiss)
```
Latency:     0.5ms p50 CPU, 0.08ms GPU for 1M vectors
Recall@10:   95-99% with proper nprobe/ef tuning
Throughput:  15K QPS (CPU), 50K+ QPS (GPU)
Memory:      3.1GB for 1M x 1536 vectors
Ops burden:  None (library, not service)
Filtering:   Must post-filter or pre-partition — no native metadata filters
Hybrid:      Not built-in; combine with external BM25
Persistence: serialize/deserialize index manually
```
**When to use**: Benchmarking, R&D, hot-path where raw speed matters and you build everything else.
**When to avoid**: Need metadata filtering, multi-tenant, or operational reliability.

#### LanceDB
```
Latency:     ~5-15ms for 1M vectors (IVF-PQ), improving with v2 indices
Recall@10:   90-97% depending on index type
Memory:      Memory-mapped columnar — low resident footprint
Ops burden:  Zero (embedded, file-based)
Filtering:   Native column filters in query (SQL-like predicates)
Hybrid:      FTS index + vector in same query pipeline
Persistence: Lance columnar format on disk
```
**When to use**: Local-first tools, single-machine agents, rapid prototyping with real persistence.
**When to avoid**: Need distributed HA or sub-millisecond latency at >10M scale.

#### pgvector (Postgres)
```
Latency:     ~10-50ms for 1M vectors (HNSW), improves with pgvectorscale
Recall@10:   95%+ with HNSW (ef_search tuning)
Memory:      Postgres shared_buffers + index; heavier than specialized engines
Ops burden:  Standard Postgres ops (backups, vacuuming, extensions)
Filtering:   Full SQL WHERE — best-in-class for complex predicates
Hybrid:      pg_trgm/tsvector FTS + pgvector in same transaction
Persistence: Full ACID, WAL, replication
```
**When to use**: Already running Postgres; need transactional guarantees; governance/audit requirements; complex joins between memory records and relational data.
**When to avoid**: Extreme vector throughput at >50M scale without pgvectorscale.

#### Qdrant
```
Latency:     ~5-10ms for 10M vectors (HNSW), sub-5ms with quantization
Recall@10:   97-99% with default HNSW params
Memory:      Configurable: full in-RAM, mmap, or on-disk with quantization
Ops burden:  Moderate (standalone binary or Docker, snapshots, replication)
Filtering:   Payload filters with indexed fields — fast
Hybrid:      Native RRF fusion (dense + sparse), weighted modes
Persistence: WAL + snapshots, distributed mode available
```
**When to use**: Production hybrid retrieval, need both dense+sparse natively, scaling beyond single Postgres.
**When to avoid**: Want zero-ops embedded deployment; small datasets where pgvector suffices.

#### Weaviate
```
Latency:     ~10-20ms for 10M objects (HNSW)
Recall@10:   95-98% with tuned ef
Memory:      Object storage + vector index, moderate footprint
Ops burden:  Moderate-high (Java runtime, schema management, modules)
Filtering:   Schema-based with inverted index
Hybrid:      Native alpha-weighted fusion (BM25 + vector)
Persistence: Disk-backed with LSM
```
**When to use**: Teams wanting a full-featured vector platform with schema enforcement and module ecosystem.
**When to avoid**: Simpler use cases; operational overhead is higher than Qdrant/pgvector.

#### Milvus
```
Latency:     ~5-15ms for 100M vectors (distributed)
Recall@10:   95-99% depending on index (IVF, HNSW, DiskANN)
Memory:      Distributed across nodes; configurable tiered storage
Ops burden:  High (etcd, MinIO/S3, message queue, multiple services)
Filtering:   Attribute filtering with index
Hybrid:      Sparse + dense vector support
Persistence: Distributed with S3-compatible storage
```
**When to use**: Massive scale (>100M vectors), multi-tenant enterprise deployments.
**When to avoid**: Small/medium projects; operational complexity is significant.

---

## Graph Store Comparison

### Decision Axes

| Backend | Deployment | Query Language | Multi-hop Perf | Embedding Support | Licensing | Best Scale Range |
|---------|-----------|---------------|----------------|-------------------|-----------|-----------------|
| **In-memory (ours)** | Embedded | Python API | Fast (<1ms) | None | MIT (ours) | <50K nodes |
| **NetworkX** | Embedded lib | Python API | Moderate | None native | BSD-3 | <500K nodes |
| **Kuzu** | Embedded DB | Cypher | Fast | Via extension | MIT | 1M–100M nodes |
| **FalkorDB** | Redis module | Cypher subset | Very fast | Native vector | Server-side PL | 1M–50M nodes |
| **Memgraph** | Standalone | Cypher | Very fast | Via MAGE | BSL/Enterprise | 1M–100M nodes |
| **Neo4j** | Standalone/Cloud | Cypher | Mature | Native (5.x+) | GPL/Commercial | 1M–1B nodes |

### Detailed Profiles

### Benchmark Summary (Q1 2026, 381K nodes / 804K edges)

Sources: AIMultiple Graph DB Benchmark (Mar 2026), Vela Partners KuzuDB Benchmark (Mar 2026, 100K nodes / 2.4M edges)

| Backend | Point Lookup | 2-hop Traversal | Concurrent QPS (8t) | Memory (381K nodes) | Cold Start |
|---------|-------------|-----------------|----------------------|---------------------|------------|
| **In-memory (ours)** | <0.1ms | <1ms | N/A (single thread) | Python dict overhead | N/A |
| **NetworkX** | <1ms | ~10ms @100K | N/A | ~1KB/node (high) | N/A |
| **Kuzu** | — | 0.009s (374x faster than Neo4j) | Single-writer | Low (mmap) | N/A |
| **FalkorDB** | 0.04ms | 2.9x faster than Neo4j | 6,693 QPS | 496MB | 1.1ms |
| **Memgraph** | ~2ms | Fast | 684 QPS | 415MB (lowest) | Moderate |
| **Neo4j** | 2-3ms | 3.22s (baseline) | 1,010 QPS | 2,668MB (JVM) | 90ms |

### Ingestion Throughput

| Backend | Throughput | Notes |
|---------|-----------|-------|
| **Kuzu** | 53x faster than Neo4j | 0.58s vs 30.64s for full dataset |
| **FalkorDB** | 22,784 ops/batch @5K | Scales steeply with batch size |
| **Memgraph** | 1,427/s | Fastest single inserts |
| **Neo4j** | ~10,600/s | Plateaus regardless of batch |

### Licensing (Critical for OSS)

| Backend | License | OSI-Approved | Can Offer as Service | Notes |
|---------|---------|-------------|----------------------|-------|
| **NetworkX** | BSD-3 | ✅ | ✅ | No restrictions |
| **Kuzu** | MIT | ✅ | ✅ | Original archived Oct 2025; Vela fork maintained |
| **FalkorDB** | Source-available (SSPL-adj) | ❌ | ❌ Restrictions | Cannot redistribute as service |
| **Memgraph** | BSL 1.1 | ❌ | ❌ Cannot offer as service | Not OSI despite "open-source" marketing |
| **Neo4j** | GPLv3 / Commercial | ❌ (Enterprise) | Requires Enterprise license | Clustering/RBAC need paid tier |
| **ArcadeDB** | Apache 2.0 | ✅ | ✅ | Multi-model (graph+doc+vector+KV) |

### Vector/Embedding Support (for GraphRAG patterns)

| Backend | Native Vector Index | Notes |
|---------|-------------------|-------|
| **FalkorDB** | ✅ HNSW (v4.0) | Vector on nodes/edges — best for unified graph+vector |
| **Neo4j** | ✅ (5.11+) | Enterprise feature; vector index on nodes |
| **ArcadeDB** | ✅ Built-in | Multi-model includes vector natively |
| **Memgraph** | ❌ | Roadmap only |
| **Kuzu** | ❌ | No vector support; pair with external vector DB |
| **NetworkX** | ❌ | Pure Python; no persistence or vector |

### Detailed Profiles

#### NetworkX (in-memory Python)
```
Traversal:   Good for <100K nodes; degrades beyond that
Memory:      ~1KB per node+edges (Python object overhead is high)
Multi-hop:   BFS/DFS/PageRank built-in; no disk persistence
Persistence: Manual pickle/JSON serialize
License:     BSD-3 (unrestricted)
```
**When to use**: Prototyping, unit tests, small knowledge graphs where Python-native API matters.
**When to avoid**: Anything beyond prototype scale; no concurrent access.

#### Kuzu (kuzudb / Vela fork)
```
Traversal:   374x faster than Neo4j on 2-hop paths (0.009s vs 3.22s)
Ingestion:   53x faster than Neo4j (0.58s vs 30.64s for full dataset)
Memory:      Memory-mapped; low resident footprint relative to graph size
Multi-hop:   Full Cypher with recursive path queries
Persistence: Embedded DB files — zero server process
Query lang:  Cypher (OpenCypher compatible)
License:     MIT (unrestricted)
```
**When to use**: Embedded graph for local-first tools, analytical graph queries, shipping with apps.
**When to avoid**: Need real-time concurrent writes from multiple processes (Vela fork addresses this); original archived Oct 2025.

#### FalkorDB
```
Traversal:   0.04ms point lookup; 2.9x faster than Neo4j on multi-hop
Throughput:  6,693 QPS concurrent (8 threads) — peaks at single-threaded Redis ceiling
Memory:      496MB for 381K nodes (Redis memory model; graph must fit in RAM)
Cold start:  1.1ms (vs Neo4j 90ms)
Multi-hop:   Cypher subset (openCypher); fast for short paths
Persistence: Redis RDB/AOF
Extras:      Native HNSW vector index on nodes/edges (GraphRAG patterns)
License:     Source-available (SSPL-adjacent) — cannot redistribute as service
```
**When to use**: Read-heavy AI/RAG workloads; need combined graph+vector on same nodes; low-latency.
**When to avoid**: Graph exceeds available RAM; need OSI-approved license; need >8 thread concurrency.

#### Memgraph
```
Traversal:   Fast in-memory; ~1ms for 3-hop on 10M edges
Throughput:  684 QPS concurrent (lower than expected)
Memory:      415MB for 381K nodes — lowest of all benchmarked (C++, no JVM)
Multi-hop:   Full Cypher; MAGE library for PageRank, community detection
Persistence: WAL + snapshots; replication in enterprise
Query lang:  Full Cypher
License:     BSL 1.1 (NOT OSI-approved) — cannot offer as service
```
**When to use**: Real-time streaming graph updates; memory-constrained environments.
**When to avoid**: Enterprise features require commercial license; BSL licensing risk; lower concurrent throughput than expected.

#### Neo4j
```
Traversal:   2-3ms point lookup; 3.22s for 2-hop on 100K nodes (374x slower than Kuzu)
Throughput:  1,010 QPS concurrent (peaks at 16 threads)
Memory:      2,668MB for 381K nodes (JVM heap pre-allocated 4GB)
Cold start:  90ms (274ms first query)
Multi-hop:   Full Cypher + GDS library (PageRank, shortest path, community)
Persistence: Full ACID transactions; clustering; backups
Extras:      Native vector index (5.11+); GraphRAG integrations; largest ecosystem
Query lang:  Cypher (industry standard)
License:     GPLv3 (Community) / Commercial (Enterprise for clustering/RBAC)
```
**When to use**: Production graph workloads needing mature tooling/community/clustering; complex analytics via GDS.
**When to avoid**: Simpler embedded use cases where Kuzu suffices; cost/licensing concerns; latency-sensitive reads.

#### ArcadeDB (honorable mention)
```
Traversal:   Competitive with Neo4j; multi-model (graph+doc+vector+KV+time-series)
Query lang:  Cypher (97.8% TCK), SQL, Gremlin, GraphQL, MQL — 5 languages
Extras:      Built-in vector search, built-in MCP server
License:     Apache 2.0 (fully OSI-approved, unrestricted)
```
**When to use**: Need multi-model in one DB; SQL-first teams; want truly open-source graph+vector.
**When to avoid**: Smaller ecosystem than Neo4j; newer project.

---

## Recommended Profiles

### Profile A: Local-First / Solo Developer
```
Vector:  LanceDB (embedded, zero-ops)
Graph:   Kuzu (embedded, Cypher)
Storage: Single directory on disk
Ops:     None
Cost:    $0
```
Best for: Personal agents, desktop tools, rapid prototyping, shipping as a single binary.

### Profile B: Small Team / Single Server
```
Vector:  pgvector (Postgres extension)
Graph:   Kuzu or FalkorDB (embedded or Redis)
Storage: Postgres + graph DB files
Ops:     Standard Postgres maintenance
Cost:    $0 (OSS) or ~$50-200/mo managed Postgres
```
Best for: Startup teams, internal tools, moderate-scale memory (<5M records).

### Profile C: Production / Multi-Tenant
```
Vector:  Qdrant (dedicated service)
Graph:   Neo4j (dedicated service)
Storage: Postgres for metadata + Qdrant for vectors + Neo4j for graph
Ops:     Moderate (3 services to manage)
Cost:    ~$200-1000/mo depending on scale
```
Best for: SaaS products, enterprise agent platforms, high-availability requirements.

### Profile D: Enterprise / Massive Scale
```
Vector:  Milvus or Qdrant Cloud
Graph:   Neo4j Enterprise or Memgraph Enterprise
Storage: Distributed across nodes
Ops:     High (dedicated infra team)
Cost:    $1000+/mo
```
Best for: >100M memory records, strict compliance/audit, multi-region deployments.

---

## Migration Path

The adapter protocol in `context-fabrica` is designed so you start with Profile A and graduate to Profile C without changing application code:

```
Profile A (prototype)     →  Profile B (team)         →  Profile C (production)
In-memory + BM25              pgvector + Kuzu              Qdrant + Neo4j
  ↓ swap adapter                ↓ swap adapter               ↓ scale horizontally
  No app code changes           No app code changes          No app code changes
```

Each adapter implements `VectorStoreAdapter` or `GraphStoreAdapter` from `adapters.py`.
The engine does not know or care which backend is active.

---

## Benchmark Sources

- Salt Technologies AI Vector Database Benchmark 2026: https://www.salttechno.ai/datasets/vector-database-performance-benchmark-2026/
- MariaDB Big Vector Search Benchmark (March 2026): https://mariadb.org/big-vector-search-benchmark-10-databases-comparison/
- AIMultiple Graph DB Benchmark (March 2026): https://aimultiple.com/graph-databases
- Vela Partners KuzuDB for AI Agents (March 2026): https://www.vela.partners/blog/kuzudb-ai-agent-memory-graph-database
- ArcadeDB Neo4j Alternatives 2026 (licensing analysis): https://arcadedb.com/blog/neo4j-alternatives-in-2026-a-fair-look-at-the-open-source-options/
- FAISS vs Qdrant 2025: https://aloa.co/ai/comparisons/vector-database-comparison/faiss-vs-qdrant
- FalkorDB GraphRAG Vector Indexes: https://medium.com/@QuarkAndCode/falkordb-vector-indexes-for-graphrag-langchain-llamaindex-5573a3e21792
