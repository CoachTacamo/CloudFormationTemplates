---
inclusion: manual
description: Explains the purpose, contents, and design rationale for the metadata/index S3 bucket in the RAG pipeline.
---

# Metadata/Index Bucket — RAG Pipeline

The metadata bucket stores the connective tissue of the RAG pipeline: the data that ties chunks, embeddings, and LLM responses back to their source documents.

## Purpose

When documents are chunked, context about origin is lost. The metadata bucket preserves that relationship so the pipeline can trace any chunk back to its source.

## What Gets Stored

Per-chunk metadata typically includes:

- Source document reference (file name, S3 key, version ID)
- Location within the document (page number, section heading, character offsets)
- Processing timestamp and pipeline version
- Document-level metadata (author, date, classification, department)

Format is usually JSON or Parquet files keyed by chunk ID or document ID.

## Why It Matters

### Citation and Provenance
Enables LLM responses to include source references (e.g., "According to [document X, page Y]..."). This is what makes RAG trustworthy in enterprise settings.

### Access Control at Query Time
If documents have different sensitivity levels, metadata enables filtering retrieval results based on the requesting user's permissions. Semantically relevant chunks from restricted documents should not surface for unauthorized users.

### Reprocessing Decisions
When a source document is updated, metadata identifies exactly which chunks need re-embedding and which vector store entries need replacement — avoiding full reprocessing.

### Debugging Retrieval Quality
When the LLM produces a poor answer, metadata enables tracing through the full chain: which chunks were retrieved, where they came from, and whether the issue was in chunking, embedding, retrieval, or generation.

## Alternatives

For simple pipelines without attribution or access control requirements, basic metadata can be stored directly in the vector store (most support arbitrary metadata alongside vectors). A dedicated bucket becomes more valuable as the document corpus grows and traceability requirements increase.

DynamoDB is another option if real-time lookups are needed. S3 is better suited for batch processing and durable, low-cost storage.
