---
inclusion: manual
description: Defines the six S3 bucket types, their purposes, and recommended CloudFormation properties for the serverless RAG pipeline.
---

# S3 Bucket Guidelines for Serverless RAG Pipeline

This document defines the six S3 bucket types used in the serverless RAG pipeline, their purpose, and the CloudFormation properties most relevant to each bucket's mission.

## General Defaults (apply to all buckets)

- PublicAccessBlockConfiguration: All four blocks enabled (BlockPublicAcls, BlockPublicPolicy, IgnorePublicAcls, RestrictPublicBuckets)
- OwnershipControls: BucketOwnerEnforced (disables ACLs)
- AbacStatus: Enabled
- BucketEncryption: SSE-S3 at minimum; use SSE-KMS if cross-account access or compliance requires it
- Tags: Environment and Project at minimum; additional tags applied at stack level
- DeletionPolicy: RetainExceptOnCreate (unless noted otherwise) — retains data buckets on stack deletion but cleans up empty buckets from failed initial deployments
- UpdateReplacePolicy: Retain (unless noted otherwise)

---

## 1. Raw/Ingestion Bucket

Landing zone for source documents (PDFs, Word, HTML, etc.). All incoming data enters the pipeline here.

- [x] BucketName: `${StackName}-raw-documents`
- [x] VersioningConfiguration: Enabled (track document revisions, support reprocessing)
- NotificationConfiguration: S3 event notifications on `s3:ObjectCreated:*` to trigger parsing Lambda or Step Functions
- ObjectLockConfiguration: Consider GOVERNANCE or COMPLIANCE mode for regulated data
- LifecycleConfiguration: Transition to Glacier/Deep Archive after processing window (e.g., 90 days to IA, 365 days to Glacier) if originals are rarely re-accessed
- CorsConfiguration: Only if documents are uploaded directly from a browser (pre-signed URLs)
- [x] DeletionPolicy: RetainExceptOnCreate (source documents are irreplaceable; must survive stack deletion but no need to retain an empty bucket from a failed create)

## 2. Processed/Chunked Bucket

Stores parsed, cleaned, and chunked text segments ready for embedding. Preserves intermediate output so re-embedding doesn't require re-parsing.

- BucketName: `${StackName}-processed-chunks`
- VersioningConfiguration: Enabled (track chunking strategy changes across reprocessing runs)
- NotificationConfiguration: S3 event notifications on `s3:ObjectCreated:*` to trigger embedding generation
- LifecycleConfiguration: Expire old noncurrent versions after a retention window (e.g., 30 days) to control storage costs from reprocessing
- DeletionPolicy: RetainExceptOnCreate (chunks are derivable from raw documents but expensive to reprocess at scale; retain once populated)

## 3. Embeddings/Vectors Bucket

Optional staging area for vector embeddings before loading into a vector store. Enables replayability, batch loading, and model versioning. Can be omitted if writing directly to the vector database.

- BucketName: `${StackName}-embeddings`
- VersioningConfiguration: Enabled (support multiple embedding model outputs for A/B testing)
- NotificationConfiguration: S3 event notifications to trigger batch upsert into vector store
- LifecycleConfiguration: Expire noncurrent versions aggressively (e.g., 14 days) since embeddings are regenerable; transition current versions to IA after 30 days if batch loading is infrequent
- DeletionPolicy: Delete — embeddings are fully regenerable from chunks + embedding model; no data loss risk. Use RetainExceptOnCreate if re-embedding cost is a concern at scale.

## 4. Metadata/Index Bucket

Stores document metadata, chunk-to-source mappings, and provenance data for citation and attribution in RAG responses.

- BucketName: `${StackName}-metadata`
- VersioningConfiguration: Enabled (metadata evolves as documents are reprocessed)
- LifecycleConfiguration: Retain current versions indefinitely; expire noncurrent versions after 90 days
- BucketEncryption: SSE-KMS recommended (metadata may contain document classification, author info, or access control attributes)
- DeletionPolicy: RetainExceptOnCreate (metadata is critical for provenance and citation; losing it breaks traceability without full reprocessing)

## 5. Pipeline Artifacts Bucket

Operational bucket for Lambda deployment packages, Step Functions definitions, configuration files, and other pipeline infrastructure assets.

- BucketName: `${StackName}-pipeline-artifacts`
- VersioningConfiguration: Enabled (track deployment history)
- DeletionPolicy: Delete (contents are reproducible from source control)
- UpdateReplacePolicy: Delete
- LifecycleConfiguration: Expire noncurrent versions after 30 days to limit storage of old deployment packages
- BucketEncryption: SSE-S3 sufficient (no sensitive data)

## 6. Logs/Audit Bucket

S3 access logs, processing logs, and audit trails. Required when handling sensitive documents or meeting compliance requirements.

- BucketName: `${StackName}-logs`
- VersioningConfiguration: Enabled
- ObjectLockConfiguration: COMPLIANCE mode with retention period matching regulatory requirements (e.g., 1 year)
- LifecycleConfiguration: Transition to IA after 30 days, Glacier after 90 days, Deep Archive after 365 days; align expiration with retention policy
- BucketEncryption: SSE-KMS (audit logs are sensitive)
- LoggingConfiguration: Do NOT enable access logging on this bucket (avoids recursive logging loop)
- NotificationConfiguration: Not typically needed; logs are consumed by analytics or compliance tools on a schedule
- DeletionPolicy: RetainExceptOnCreate (audit data must survive stack deletion for compliance; Object Lock provides additional protection)
