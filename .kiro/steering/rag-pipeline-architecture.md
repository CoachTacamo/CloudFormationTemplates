---
inclusion: auto
description: Defines the AWS services, integration patterns, and design decisions for the serverless RAG pipeline architecture.
---

# Serverless RAG Pipeline — Architecture & Service Guidelines

This document defines the AWS services, their roles, and integration patterns for the serverless RAG pipeline. Use it as the reference when building or modifying any part of the pipeline.

## Architecture Overview

The pipeline has two paths:

**Ingestion Path** (async, event-driven):
```
S3 (upload) → EventBridge/S3 Event → Step Functions → Lambda (parse) → Lambda (chunk) → Bedrock (embed) → OpenSearch Serverless (index)
```

**Query Path** (sync, request-response):
```
API Gateway → Lambda (query) → Bedrock (embed query) → OpenSearch Serverless (search) → Bedrock (generate) → Response
```

Metadata and provenance flow through DynamoDB and the metadata S3 bucket throughout both paths.

---

## Core Services

### AWS Lambda

The compute backbone. Each Lambda handles a single responsibility in the pipeline.

| Function | Purpose | Trigger |
|---|---|---|
| Document Parser | Extract text from raw documents (PDF, DOCX, HTML) | Step Functions |
| Chunker | Split parsed text into overlapping segments | Step Functions |
| Embedding Generator | Call Bedrock embedding model per chunk batch | Step Functions / SQS |
| Index Writer | Upsert vectors into OpenSearch Serverless | Step Functions / SQS |
| Query Handler | Orchestrate retrieval and generation for user queries | API Gateway |

Guidelines:
- Memory: 512 MB minimum for parsing; 256 MB for lightweight functions
- Timeout: 60s for parsing/chunking, 120s for embedding (Bedrock latency), 30s for query
- Runtime: Python 3.12 or Node.js 20.x
- Use Lambda Powertools for structured logging, tracing, and metrics
- Package shared logic (chunking strategies, Bedrock client wrappers) as Lambda Layers

### AWS Step Functions

Orchestrates the ingestion pipeline. Preferred over chaining Lambdas directly because:
- Built-in retry and error handling per step
- Visual execution history for debugging
- Handles long-running document processing without Lambda timeout pressure (via Map state for batch processing)

Pattern:
- Use Standard Workflows (not Express) for ingestion — documents may take minutes to fully process
- Use Express Workflows for query orchestration if latency is critical and execution is under 5 minutes
- Use Map state for parallel chunk processing within a single document
- Use Distributed Map for processing multiple documents concurrently

### Amazon Bedrock

Provides both embedding and generation models without managing infrastructure.

| Capability | Model | Notes |
|---|---|---|
| Embeddings | Amazon Titan Embeddings V2 | 1024-dimension vectors, good cost/performance balance |
| Generation | Anthropic Claude (via Bedrock) | Use for answer synthesis from retrieved context |

Guidelines:
- Request Bedrock model access in advance — it requires approval per model per region
- Use batch inference for bulk embedding during ingestion; real-time inference for queries
- Set `max_tokens` conservatively on generation calls to control cost
- Implement exponential backoff — Bedrock has per-model throttling limits

### Amazon OpenSearch Serverless

Vector store for similarity search. Use a vector search collection type.

Guidelines:
- Collection type: VECTORSEARCH
- Create a data access policy scoping Lambda execution roles to the collection
- Create a network policy — use VPC endpoint if Lambdas run in a VPC, otherwise public access with IAM auth
- Index mapping: use `knn_vector` field type with dimension matching your embedding model (1024 for Titan V2)
- Engine: FAISS or nmslib (FAISS recommended for large-scale)
- Use `k-NN` plugin settings: `ef_search` of 512 for quality, lower for speed
- Encryption policy: AWS owned key is fine unless compliance requires CMK

### Amazon API Gateway

Exposes the query endpoint. Use HTTP API (not REST API) for lower latency and cost.

Guidelines:
- Use Lambda proxy integration
- Enable IAM authorization or Cognito authorizer — no open endpoints
- Set throttling: start with 100 requests/second, adjust based on load
- Enable access logging to the logs bucket
- Use request validation to reject malformed queries early

### Amazon SQS

Decouples ingestion steps when Step Functions alone isn't sufficient, particularly for:
- Buffering embedding requests to stay within Bedrock throttle limits
- Dead-letter queues for failed processing steps
- Fan-out when a single document produces hundreds of chunks

Guidelines:
- Use Standard queues (ordering isn't critical for chunk processing)
- Set visibility timeout to 6x the consuming Lambda's timeout
- Configure a DLQ with `maxReceiveCount` of 3
- Enable SSE-SQS encryption

### Amazon DynamoDB

Tracks document processing state and metadata for real-time lookups.

| Table | Partition Key | Sort Key | Purpose |
|---|---|---|---|
| Documents | documentId | — | Processing status, source S3 key, timestamps |
| Chunks | documentId | chunkId | Chunk-to-document mapping, vector store IDs |

Guidelines:
- Use on-demand capacity mode (serverless, no capacity planning)
- Enable point-in-time recovery
- Enable DynamoDB Streams if downstream consumers need change notifications
- TTL on chunks table if embeddings are regenerated periodically

### Amazon EventBridge

Triggers the pipeline on S3 uploads without coupling S3 directly to Step Functions.

Guidelines:
- Use S3 Event Notifications to EventBridge (enable on the raw documents bucket)
- Create a rule matching `s3:ObjectCreated:*` events filtered to the raw bucket
- Target: Step Functions state machine
- Advantage over direct S3→Lambda: supports multiple targets, filtering, replay

---

## Optional / Situational Services

### Amazon Textract
Use when ingesting scanned PDFs or images. Adds a step before chunking to extract text via OCR. Increases cost and latency — only enable for document types that need it.

### Amazon CloudWatch
Non-optional in practice. All Lambdas log here by default. Add:
- Custom metrics for: documents processed, chunks generated, embedding latency, query latency, retrieval relevance scores
- Alarms on: DLQ message count > 0, Lambda error rate > 1%, Step Functions execution failures
- Dashboard consolidating pipeline health

### AWS X-Ray
Enable active tracing on Lambda and Step Functions for end-to-end request tracing across the pipeline. Critical for debugging latency in the query path.

---

## Infrastructure as Code

All resources are defined in CloudFormation (or SAM) templates. The current stack structure:

- `storage-stack.json` — S3 buckets (see #[[file:.kiro/steering/s3-bucket-guidelines.md]])
- `ingestion-lambda-stack.json` — Lambda functions and layers for the ingestion path
- `rag-pipeline-orchestrator-stack.json` — Step Functions, EventBridge rules, SQS queues
- `rag-pipeline-packaged-stack.json` — Packaged/deployable version of the full pipeline

Guidelines:
- Use cross-stack references (Exports/Imports) to share resource ARNs between stacks
- Tag all resources with `Environment` and `Project`
- Use `AWS::Serverless::Function` (SAM) where possible for simpler Lambda definitions
- Validate templates with cfn-lint before deployment
- Check compliance with cfn-guard for security controls

---

## Key Design Decisions

1. **Serverless-first**: No EC2, no ECS, no self-managed clusters. Every service is managed/serverless.
2. **Event-driven ingestion**: Documents flow through the pipeline via events, not polling.
3. **Sync queries, async ingestion**: Query path is request-response through API Gateway. Ingestion is fully asynchronous.
4. **Embedding model portability**: Store embeddings in S3 as an intermediate step so switching models doesn't require re-parsing and re-chunking.
5. **Metadata separation**: Provenance data lives in DynamoDB (real-time lookups) and S3 (batch/archive). See #[[file:.kiro/steering/metadata-index-bucket.md]] for details.
