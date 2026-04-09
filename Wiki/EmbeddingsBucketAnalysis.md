# Embeddings/Vectors S3 Bucket: Keep or Skip?

An analysis of whether the `${StackName}-embeddings` bucket adds enough value to justify its place in the pipeline, versus writing embeddings directly to the vector database.

## Context

The current pipeline flow is: Raw Documents → Processed Chunks → **Embeddings Bucket** → Vector Database. The question is whether that middle step earns its keep or just adds latency and cost.

## Case For Keeping the Bucket

### Replayability Without Re-Embedding

Embedding generation costs real money (API calls to Bedrock, OpenAI, etc.) and takes time. If the vector database needs to be rebuilt — schema migration, index corruption, switching from OpenSearch to pgvector — having embeddings on S3 means you reload rather than regenerate. At scale (millions of chunks), this saves hours and significant API cost.

### Embedding Model A/B Testing

When evaluating a new embedding model (e.g., moving from Titan to Cohere), you can generate both sets of embeddings, store them side-by-side in S3 keyed by model version, and compare retrieval quality before committing. Without the bucket, you'd need to re-embed the entire corpus every time you want to test a model swap.

### Batch Loading and Rate Limiting

Vector databases have write throughput limits. S3 acts as a buffer that decouples embedding generation speed from database ingestion speed. A Lambda or Step Function can read from the bucket and batch-upsert at a pace the database can handle, with retries and backoff, without losing any embeddings if the DB is temporarily unavailable.

### Audit Trail and Debugging

When retrieval quality degrades, having the raw embedding vectors on S3 lets you inspect what was actually indexed. You can compare the stored vectors against what's in the database to detect drift, partial loads, or corruption. Without this, debugging means re-embedding and hoping to reproduce the issue.

### Decoupled Pipeline Stages

Each stage of the pipeline (parse → chunk → embed → index) can fail and retry independently. If the vector DB upsert fails, the embeddings are safe on S3. If you need to reprocess only the indexing step, you don't touch the upstream stages. This is standard event-driven architecture — S3 notifications trigger the next step only when the previous one succeeds.

### Cost of Re-Embedding at Scale

For a corpus of 1M chunks using Amazon Titan Embeddings v2, re-embedding costs roughly $10–15 per full run. That's manageable once, but if you're iterating on chunking strategies, testing models, or rebuilding indexes monthly, it compounds. The S3 storage cost for those same embeddings is pennies per month.

---

## Case Against the Bucket

### Added Latency

Every document now has an extra write-then-read hop: serialize embeddings to JSON/Parquet → PUT to S3 → S3 event notification → Lambda reads from S3 → upsert to DB. For real-time or near-real-time ingestion, this adds seconds of latency per document that a direct write to the vector DB avoids.

### Operational Complexity

More moving parts means more things to break. The S3 notification, the batch loading Lambda, the serialization format — each is a surface area for bugs. A direct `embed → upsert` Lambda is simpler to build, test, and monitor. For a small team, simplicity has real value.

### Embeddings Are Regenerable

Unlike raw documents, embeddings are derived data. Given the chunks and the model, you can always regenerate them. The steering doc already acknowledges this with `DeletionPolicy: Delete`. If you accept they're disposable, the argument for storing them weakens — you're caching something you can recompute.

### Storage Format Overhead

Embedding vectors are dense floating-point arrays. Storing them as JSON in S3 is space-inefficient (a 1536-dim float32 vector is ~6KB binary but ~15KB as JSON). Parquet or binary formats help, but add serialization complexity. The vector database already stores them in an optimized format.

### Small Corpus Doesn't Justify It

If your document corpus is in the thousands (not millions), re-embedding the entire thing takes minutes and costs under a dollar. The replayability argument only becomes compelling at scale. For an early-stage pipeline, the bucket is premature optimization.

### Vector DB Already Handles Versioning

Most vector databases (OpenSearch, Pinecone, pgvector) support namespaces, indexes, or collections. You can maintain multiple embedding model versions within the DB itself, without needing S3 as a staging area.

---

## Recommendation Framework

| Factor | Keep the Bucket | Skip It |
|---|---|---|
| Corpus size | > 100K chunks | < 100K chunks |
| Embedding model changes | Frequent experimentation | Settled on one model |
| Ingestion pattern | Batch (daily/weekly) | Real-time per document |
| Vector DB stability | New/migrating | Stable, proven setup |
| Re-embedding budget tolerance | Low (cost-sensitive) | High (can absorb re-runs) |
| Team size / ops capacity | Can manage extra infra | Prefer fewer components |

## Bottom Line

The bucket is a legitimate architectural choice, not filler. It trades simplicity for resilience and cost efficiency at scale. But it's genuinely optional for smaller pipelines or teams that value fewer moving parts. The steering doc already flags it as optional — the right call depends on where this pipeline is headed, not where it is today.

If you expect the corpus to grow significantly or anticipate model experimentation, keep it. If this is a focused pipeline with a stable model and a small corpus, skip it and add it later if the need materializes.
