---
inclusion: manual
---

# RAG Pipeline — Deployment Milestones

Deployment order for the serverless RAG pipeline, organized by dependency layers.
Each layer must be fully deployed before the next layer can begin, unless noted otherwise.

---

## Layer 1 — Foundation (no cross-dependencies, deploy in parallel)

### Milestone 1.1: S3 Buckets (`storage-stack`)
- **Stack:** `storage-stack.json`
- **Status:** ✅ Exists
- **Resources:** RawDocuments, ProcessedDocuments, EmbeddingsVectors, MetadataIndex, PipelineArtifacts, LogsAudit buckets
- **Gateway Endpoint:** S3 Gateway Endpoint included in this stack, attached to `PrivateRouteTableId` for VPC-internal S3 access
- **Exports:** Bucket names and ARNs consumed by all downstream stacks

### Milestone 1.2: OpenSearch Serverless (`opensearch-stack`)
- **Stack:** `opensearch-stack.json`
- **Status:** ✅ Exists
- **Resources:** VECTORSEARCH collection, encryption policy, network policy, data access policy
- **Exports:** CollectionId, CollectionArn, CollectionEndpoint, DashboardEndpoint
- **Note:** Encryption and network policies must exist before the collection (handled via `DependsOn` within the stack)

### Milestone 1.3: DynamoDB Tables
- **Stack:** `dynamodb-stack.json`
- **Status:** ✅ Exists
- **Resources needed:**
  - `Documents` table (PK: `documentId`) — processing status, source S3 key, timestamps
  - `Chunks` table (PK: `documentId`, SK: `chunkId`) — chunk-to-document mapping, vector store IDs
- **Gateway Endpoint:** DynamoDB Gateway Endpoint needed in this stack, attached to `PrivateRouteTableId` for VPC-internal DynamoDB access
- **Config:** On-demand capacity, point-in-time recovery, DynamoDB Streams enabled
- **Exports:** Table names, ARNs, stream ARNs

### Milestone 1.4: Bedrock Model Access (`bedrock-access-stack`)
- **Stack:** `bedrock-access-stack.json` (nested in orchestrator)
- **Status:** ✅ Done
- **Resources:** Custom Resource (Lambda-backed) that calls `ListFoundationModelAgreementOffers` and `CreateFoundationModelAgreement` per model on create, `DeleteFoundationModelAgreement` on teardown
- **Models enabled:**
  - `amazon.titan-embed-text-v2:0` (embeddings, 1024 dimensions)
  - `amazon.nova-pro-v1:0` (answer generation — replaces Claude due to GovCloud governmental limitations)
- **GovCloud note:** Simplified auto-access from commercial regions does not apply in GovCloud; this stack handles the manual enablement programmatically
- **Exports:** EmbeddingModelId, GenerationModelId

---

## Layer 2 — Compute (depends on Layer 1)

### Milestone 2.1: Ingestion Lambda Functions (`ingestion-lambda-stack`)
- **Stack:** `ingestion-lambda-stack.json`
- **Status:** ✅ Exists (partial — only document ingestion, not chunking/embedding)
- **Depends on:** `storage-stack` (imports bucket ARNs/names)

### Milestone 2.0: ImportDocuments Lambda (`import-documents-stack`)
- **Stack:** `import-documents-stack.json`
- **Status:** ✅ Done
- **Depends on:** `storage-stack` (imports bucket ARNs/names via `Fn::ImportValue`)
- **Resources:** ImportDocuments Lambda (Python 3.12), IAM execution role, CloudWatch Logs VPC endpoint, Secrets Manager VPC endpoint
- **VPC:** Lambda deployed into private subnets with IT-managed security group
- **Secret management:** Client secret retrieved from Secrets Manager at runtime via `clientSecretArn` env var
- **Exports:** Function ARN/name, Role ARN, VPC endpoint IDs

### Milestone 2.1a: Remaining Ingestion Lambdas
- **Status:** ❌ Not yet created
- **Still needed:**
  - Chunker Lambda — split parsed text into overlapping segments
  - Embedding Generator Lambda — call Bedrock embedding model per chunk batch
  - Index Writer Lambda — upsert vectors into OpenSearch Serverless
- **Each Lambda needs:** IAM roles with scoped access to S3, OpenSearch, Bedrock, DynamoDB

### Milestone 2.2: SQS Queues + Dead Letter Queues
- **Stack:** TBD — can live in `ingestion-lambda-stack` or a dedicated `messaging-stack.json`
- **Status:** ❌ Not yet created
- **Resources needed:**
  - Embedding request buffer queue (standard, SSE-SQS encrypted)
  - DLQ per processing queue (`maxReceiveCount: 3`)
- **Config:** Visibility timeout = 6× consuming Lambda timeout
- **Exports:** Queue ARNs, DLQ ARNs

---

## Layer 3 — Orchestration (depends on Layers 1 + 2)

### Milestone 3.1: Step Functions State Machine
- **Stack:** TBD — update `rag-pipeline-orchestrator-stack.json`
- **Status:** ❌ Not yet created (orchestrator stack currently only nests storage)
- **Resources needed:**
  - Standard Workflow state machine for ingestion pipeline
  - Map state for parallel chunk processing per document
  - Distributed Map for multi-document concurrent processing
  - Error handling and retry policies per step
- **Depends on:** All Lambda ARNs, SQS queue ARNs

### Milestone 3.2: EventBridge Rules
- **Stack:** TBD — lives in orchestrator stack
- **Status:** ❌ Not yet created
- **Resources needed:**
  - S3 Event Notifications → EventBridge (enable on raw documents bucket)
  - Rule matching `s3:ObjectCreated:*` filtered to raw bucket
  - Target: Step Functions state machine ARN
- **Depends on:** Raw documents bucket, Step Functions state machine

---

## Layer 4 — Query Path (depends on Layers 1 + 2)

### Milestone 4.1: Query Lambda
- **Stack:** TBD — `query-lambda-stack.json`
- **Status:** ❌ Not yet created
- **Resources needed:**
  - Query Handler Lambda — orchestrate retrieval (OpenSearch) and generation (Bedrock)
  - IAM role with access to OpenSearch, Bedrock, DynamoDB
- **Config:** Timeout 30s, memory 512MB

### Milestone 4.2: API Gateway
- **Stack:** TBD — can bundle with query Lambda stack
- **Status:** ❌ Not yet created
- **Resources needed:**
  - HTTP API (not REST API — lower latency, lower cost)
  - Lambda proxy integration to Query Handler
  - IAM or Cognito authorizer (no open endpoints)
  - Throttling: 100 req/s baseline
  - Access logging to LogsAudit bucket
  - Request validation

---

## Layer 5 — Observability (deploy anytime, most useful after Layers 1–4)

### Milestone 5.1: Monitoring & Alerting
- **Stack:** TBD — `observability-stack.json`
- **Status:** ❌ Not yet created
- **Resources needed:**
  - CloudWatch dashboard consolidating pipeline health
  - Custom metrics: documents processed, chunks generated, embedding latency, query latency
  - Alarms: DLQ message count > 0, Lambda error rate > 1%, Step Functions execution failures
  - X-Ray active tracing on Lambda and Step Functions

---

## Layer 6 — Policy & Hardening (deploy after all resource stacks are in place)

### Milestone 6.1: VPC Endpoint Policies
- **Stack:** TBD — `policy-hardening-stack.json`
- **Status:** ❌ Not yet created
- **Resources needed:**
  - Custom resource (Lambda-backed) to call `ModifyVpcEndpoint` and apply scoped-down endpoint policies
  - DynamoDB gateway endpoint policy — restrict to Lambda execution role ARNs and specific table ARNs
  - S3 gateway endpoint policy — restrict to pipeline role ARNs and bucket ARNs
  - OpenSearch VPC endpoint policy — scope to collection ARNs and pipeline roles
- **Depends on:** All Lambda execution role ARNs (Layers 2 + 4), all resource ARNs (Layer 1)
- **Pattern:** Endpoints are created with default allow-all policies in their respective stacks; this stack imports endpoint IDs + role ARNs via cross-stack references and tightens them

### Milestone 6.2: Resource Policies & Permissions Boundaries
- **Stack:** Same `policy-hardening-stack.json` or dedicated `iam-hardening-stack.json`
- **Status:** ❌ Not yet created
- **Resources needed:**
  - DynamoDB resource policies scoping access to pipeline roles only
  - S3 bucket policies denying access from outside the VPC endpoints
  - Permissions boundaries on Lambda execution roles to cap maximum privileges
- **Depends on:** All IAM roles and resource ARNs from Layers 1–5

### Milestone 6.3: Encryption & Compliance Audit
- **Stack:** Can be part of `policy-hardening-stack.json`
- **Status:** ❌ Not yet created
- **Actions:**
  - Verify SSE is enabled on all DynamoDB tables (SSE-KMS if compliance requires CMK)
  - Verify S3 bucket encryption defaults (SSE-S3 or SSE-KMS)
  - Verify OpenSearch encryption policy uses AWS-owned key or CMK per requirements
  - Validate all templates with `cfn-guard` security rules before final deployment
- **Note:** Mostly a validation pass, but may produce CloudFormation updates if gaps are found

---

## Summary: What Exists vs What's Missing

| Layer | Stack | Status |
|-------|-------|--------|
| 1 | `storage-stack.json` | ✅ Done |
| 1 | `opensearch-stack.json` | ✅ Done |
| 1 | `dynamodb-stack.json` | ✅ Done |
| 1 | `bedrock-access-stack.json` | ✅ Done |
| 2 | `import-documents-stack.json` | ✅ Done |
| 2 | `ingestion-lambda-stack.json` | 🟡 Partial |
| 2 | SQS queues + DLQs | ❌ Missing |
| 3 | Step Functions (orchestrator) | ❌ Missing |
| 3 | EventBridge rules | ❌ Missing |
| 4 | Query Lambda | ❌ Missing |
| 4 | API Gateway | ❌ Missing |
| 5 | Observability | ❌ Missing |
| 6 | VPC endpoint policies | ❌ Missing |
| 6 | Resource policies & permissions boundaries | ❌ Missing |
| 6 | Encryption & compliance audit | ❌ Missing |
