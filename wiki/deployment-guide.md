# RAG Pipeline Deployment Guide

This guide walks through deploying the serverless RAG pipeline from scratch. The pipeline is a set of nested CloudFormation stacks orchestrated by a single parent template.

---

## Architecture at a Glance

The parent stack (`rag-pipeline-orchestrator-stack.json`) deploys six nested stacks:

| Nested Stack | What It Creates |
|---|---|
| StorageStack | Six S3 buckets (raw docs, processed docs, embeddings, metadata, logs, pipeline artifacts) + S3 gateway VPC endpoint |
| DynamoDBStack | Documents table, Chunks table + DynamoDB gateway VPC endpoint |
| OpenSearchStack | OpenSearch Serverless vector search collection, VPC endpoint, encryption/network/data-access policies |
| RDSStack | PostgreSQL 16.8 on db.t4g.small, DB subnet group, enhanced monitoring role, Secrets Manager managed credentials |
| BedrockAccessStack | Custom resource Lambda that enables Bedrock model access (Titan Embeddings V2 + Nova Pro) |
| ImportDocumentsStack | SharePoint-to-S3 import Lambda, CloudWatch Logs VPC endpoint, Secrets Manager VPC endpoint |

---

## Prerequisites

Before you begin, make sure you have:

1. **AWS CLI v2** installed and configured with credentials that have the deployer policy attached (see `Policies/` folder).
2. **A VPC** with two private subnets in different AZs, a private route table, and an internal security group. If you don't have one, deploy the VPC stack first (see Step 1).
3. **Bedrock model access** — the stack automates this, but your account must be in a region that supports Amazon Titan Embeddings V2 and Amazon Nova Pro.
4. **SharePoint credentials** (for the ImportDocuments stack) — an Azure AD tenant ID, client ID, and a client secret stored in AWS Secrets Manager.
5. **An S3 bucket** for CloudFormation nested stack templates (used by `aws cloudformation package`).

---

## Step 0 — Attach the Deployer IAM Policy

Three policy variants are provided in the `Policies/` directory:

| File | Use When |
|---|---|
| `rag-pipeline-deployer-policy.json` | Standard commercial AWS regions |
| `rag-pipeline-deployer-policy-greenfield.json` | New accounts with tighter resource scoping |
| `rag-pipeline-deployer-policy-govcloud.json` | AWS GovCloud (US) regions |

Attach the appropriate policy to your deployer IAM user or role.

### Worked Example

```bash
# Create the policy
aws iam create-policy \
  --policy-name rag-pipeline-deployer \
  --policy-document file://Policies/rag-pipeline-deployer-policy.json

# Attach to your deployer role (replace ACCOUNT_ID and ROLE_NAME)
aws iam attach-role-policy \
  --role-name ROLE_NAME \
  --policy-arn arn:aws:iam::ACCOUNT_ID:policy/rag-pipeline-deployer
```

---

## Step 1 — Deploy the VPC Stack (if needed)

Skip this step if your organization already provides a VPC with private subnets. The template is in `Special Stacks/vpc-stack.json`.

```bash
aws cloudformation deploy \
  --template-file "Special Stacks/vpc-stack.json" \
  --stack-name rag-vpc-stack \
  --parameter-overrides \
      EnvironmentName=rag-vpc-stack \
      VpcCidr=10.0.0.0/16 \
      SubnetACidr=10.0.1.0/24 \
      SubnetBCidr=10.0.2.0/24
```

### Worked Example — Retrieving VPC Outputs

After the stack completes, grab the output values you'll need for the pipeline stack:

```bash
# Get all outputs at once
aws cloudformation describe-stacks \
  --stack-name rag-vpc-stack \
  --query "Stacks[0].Outputs" \
  --output table

# Or grab individual values
VPC_ID=$(aws cloudformation describe-stacks \
  --stack-name rag-vpc-stack \
  --query "Stacks[0].Outputs[?OutputKey=='VpcId'].OutputValue" \
  --output text)

SUBNET_A=$(aws cloudformation describe-stacks \
  --stack-name rag-vpc-stack \
  --query "Stacks[0].Outputs[?OutputKey=='PrivateSubnetAId'].OutputValue" \
  --output text)

SUBNET_B=$(aws cloudformation describe-stacks \
  --stack-name rag-vpc-stack \
  --query "Stacks[0].Outputs[?OutputKey=='PrivateSubnetBId'].OutputValue" \
  --output text)

ROUTE_TABLE=$(aws cloudformation describe-stacks \
  --stack-name rag-vpc-stack \
  --query "Stacks[0].Outputs[?OutputKey=='PrivateRouteTableId'].OutputValue" \
  --output text)

SECURITY_GROUP=$(aws cloudformation describe-stacks \
  --stack-name rag-vpc-stack \
  --query "Stacks[0].Outputs[?OutputKey=='InternalSecurityGroupId'].OutputValue" \
  --output text)

echo "VPC_ID=$VPC_ID"
echo "SUBNET_A=$SUBNET_A"
echo "SUBNET_B=$SUBNET_B"
echo "ROUTE_TABLE=$ROUTE_TABLE"
echo "SECURITY_GROUP=$SECURITY_GROUP"
```

---

## Step 2 — Store the SharePoint Client Secret

The ImportDocuments Lambda needs an Azure AD client secret in Secrets Manager.

```bash
aws secretsmanager create-secret \
  --name rag-pipeline/sharepoint-client-secret \
  --description "Azure AD client secret for SharePoint import" \
  --secret-string "YOUR_CLIENT_SECRET_VALUE"
```

### Worked Example

```bash
# Create the secret and capture the ARN
CLIENT_SECRET_ARN=$(aws secretsmanager create-secret \
  --name rag-pipeline/sharepoint-client-secret \
  --secret-string "abc123-your-secret-here" \
  --query "ARN" \
  --output text)

echo "CLIENT_SECRET_ARN=$CLIENT_SECRET_ARN"
# Output: arn:aws:secretsmanager:us-east-1:123456789012:secret:rag-pipeline/sharepoint-client-secret-AbCdEf
```

---

## Step 3 — Package the Nested Stack Templates

CloudFormation nested stacks require that child templates are uploaded to S3. The `aws cloudformation package` command handles this automatically.

```bash
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket YOUR_CFN_ARTIFACTS_BUCKET \
  --output-template-file rag-pipeline-packaged-stack.json
```

This rewrites the local `TemplateURL` references (e.g., `bedrock-access-stack.json`) to S3 URLs pointing at the uploaded templates.

### Worked Example

```bash
# Create an S3 bucket for CloudFormation artifacts (one-time setup)
aws s3 mb s3://my-org-cfn-artifacts-us-east-1

# Package — uploads all nested templates to S3
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket my-org-cfn-artifacts-us-east-1 \
  --output-template-file rag-pipeline-packaged-stack.json

# Verify the packaged template has S3 URLs
grep "TemplateURL" rag-pipeline-packaged-stack.json
# Should show https://s3.amazonaws.com/my-org-cfn-artifacts-us-east-1/...
```

---

## Step 4 — Upload the ImportDocuments Lambda Code

The ImportDocuments Lambda is deployed from a zip in the pipeline artifacts bucket. You need to zip and upload the code before deploying the stack.

```bash
# Zip the Lambda code
cd lambda/import_documents
zip -r ../../import-documents-lambda.zip .
cd ../..

# Upload to the pipeline artifacts bucket (created by StorageStack)
# NOTE: On first deploy, you'll need to upload to your CFN artifacts bucket
# and update the S3 key after StorageStack creates the pipeline-artifacts bucket.
aws s3 cp import-documents-lambda.zip \
  s3://YOUR_ARTIFACTS_BUCKET/lambda/import-documents-lambda.zip
```

### Worked Example

```bash
# Zip it up
cd lambda/import_documents
zip -r ../../import-documents-lambda.zip *.py
cd ../..

# Upload to your artifacts bucket
aws s3 cp import-documents-lambda.zip \
  s3://my-org-cfn-artifacts-us-east-1/lambda/import-documents-lambda.zip

# Confirm the upload
aws s3 ls s3://my-org-cfn-artifacts-us-east-1/lambda/
# 2026-04-22 10:30:00      12345 import-documents-lambda.zip
```

---

## Step 5 — Deploy the Pipeline Stack

This is the main event. The orchestrator stack deploys all six nested stacks.

```bash
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name rag-dev-pipeline \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      ProjectPrefix=rag-dev \
      EnvironmentTag=Development \
      DeploymentDate=04-22-2026 \
      VpcId=$VPC_ID \
      PrivateSubnetAId=$SUBNET_A \
      PrivateSubnetBId=$SUBNET_B \
      PrivateRouteTableId=$ROUTE_TABLE \
      InternalSGId=$SECURITY_GROUP \
      StandbyReplicas=DISABLED \
      RdsMultiAZ=false \
      RdsDeletionProtection=false \
      RdsMasterUsername=pgadmin \
      RdsKmsKeyArn="" \
      TenantId=YOUR_AZURE_TENANT_ID \
      ClientId=YOUR_AZURE_CLIENT_ID \
      ClientSecretArn=$CLIENT_SECRET_ARN \
      SharepointUrl=https://yourorg.sharepoint.com/sites/yoursite \
      DriveName=Documents \
      ImportDocumentsLambdaS3Key=lambda/import-documents-lambda.zip \
      CsvCategories="" \
      SharePointFolderPath=""
```

### Worked Example — Development Environment

```bash
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name rag-dev-pipeline \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      ProjectPrefix=rag-dev \
      EnvironmentTag=Development \
      DeploymentDate=04-22-2026 \
      VpcId=vpc-0abc123def456 \
      PrivateSubnetAId=subnet-0aaa111 \
      PrivateSubnetBId=subnet-0bbb222 \
      PrivateRouteTableId=rtb-0ccc333 \
      InternalSGId=sg-0ddd444 \
      StandbyReplicas=DISABLED \
      RdsMultiAZ=false \
      RdsDeletionProtection=false \
      RdsMasterUsername=pgadmin \
      RdsKmsKeyArn="" \
      TenantId=a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
      ClientId=12345678-abcd-efgh-ijkl-9876543210ab \
      ClientSecretArn=arn:aws:secretsmanager:us-east-1:123456789012:secret:rag-pipeline/sharepoint-client-secret-AbCdEf \
      SharepointUrl=https://contoso.sharepoint.com/sites/engineering \
      DriveName=Documents \
      ImportDocumentsLambdaS3Key=lambda/import-documents-lambda.zip \
      CsvCategories="" \
      SharePointFolderPath=""
```

### Worked Example — Production Environment

```bash
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name rag-prod-pipeline \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      ProjectPrefix=rag-prod \
      EnvironmentTag=Production \
      DeploymentDate=04-22-2026 \
      VpcId=vpc-0prod123 \
      PrivateSubnetAId=subnet-0prod-a \
      PrivateSubnetBId=subnet-0prod-b \
      PrivateRouteTableId=rtb-0prod \
      InternalSGId=sg-0prod \
      StandbyReplicas=ENABLED \
      RdsMultiAZ=true \
      RdsDeletionProtection=true \
      RdsMasterUsername=pgadmin \
      RdsKmsKeyArn=arn:aws:kms:us-east-1:123456789012:key/your-cmk-id \
      TenantId=a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
      ClientId=12345678-abcd-efgh-ijkl-9876543210ab \
      ClientSecretArn=arn:aws:secretsmanager:us-east-1:123456789012:secret:prod/sharepoint-secret-XyZ \
      SharepointUrl=https://contoso.sharepoint.com/sites/engineering \
      DriveName=Documents \
      ImportDocumentsLambdaS3Key=lambda/import-documents-lambda.zip \
      CsvCategories="" \
      SharePointFolderPath=""
```

Key differences for production:
- `StandbyReplicas=ENABLED` — OpenSearch HA (doubles cost)
- `RdsMultiAZ=true` — automatic failover for PostgreSQL
- `RdsDeletionProtection=true` — prevents accidental deletion
- `RdsKmsKeyArn` — use a customer-managed KMS key for compliance

---

## Step 6 — Monitor the Deployment

The full stack takes approximately 15–25 minutes. OpenSearch Serverless collection creation is typically the longest step.

```bash
# Watch stack events in real time
aws cloudformation describe-stack-events \
  --stack-name rag-dev-pipeline \
  --query "StackEvents[?ResourceStatus=='CREATE_FAILED']" \
  --output table

# Check overall status
aws cloudformation describe-stacks \
  --stack-name rag-dev-pipeline \
  --query "Stacks[0].StackStatus" \
  --output text
```

### Worked Example — Tail Events

```bash
# Poll every 30 seconds until complete
while true; do
  STATUS=$(aws cloudformation describe-stacks \
    --stack-name rag-dev-pipeline \
    --query "Stacks[0].StackStatus" \
    --output text 2>/dev/null)

  echo "$(date +%H:%M:%S) — $STATUS"

  if [[ "$STATUS" == *"COMPLETE"* ]] || [[ "$STATUS" == *"FAILED"* ]] || [[ "$STATUS" == *"ROLLBACK"* ]]; then
    break
  fi

  sleep 30
done

# If it failed, find the root cause
aws cloudformation describe-stack-events \
  --stack-name rag-dev-pipeline \
  --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].{Resource:LogicalResourceId,Reason:ResourceStatusReason}" \
  --output table
```

---

## Step 7 — Validate the Deployment

Once the stack reaches `CREATE_COMPLETE`, verify the key resources.

```bash
# List all stack outputs
aws cloudformation describe-stacks \
  --stack-name rag-dev-pipeline \
  --query "Stacks[0].Outputs" \
  --output table
```

### Worked Example — Spot-Check Resources

```bash
# Verify S3 buckets exist
aws s3 ls | grep rag-dev

# Verify DynamoDB tables
aws dynamodb describe-table --table-name rag-dev-documents --query "Table.TableStatus"
aws dynamodb describe-table --table-name rag-dev-chunks --query "Table.TableStatus"

# Verify OpenSearch collection
aws opensearchserverless list-collections \
  --query "collectionSummaries[?name=='rag-dev-vectors']"

# Verify RDS instance
aws rds describe-db-instances \
  --db-instance-identifier rag-dev-pg-04-22-2026 \
  --query "DBInstances[0].DBInstanceStatus"

# Verify the ImportDocuments Lambda
aws lambda get-function \
  --function-name rag-dev-import-documents \
  --query "Configuration.{State:State,Runtime:Runtime,MemorySize:MemorySize}"

# Test-invoke the ImportDocuments Lambda (dry run)
aws lambda invoke \
  --function-name rag-dev-import-documents \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/import-response.json

cat /tmp/import-response.json
```

---

## Step 8 — Updating the Stack

To update an existing deployment, re-package and re-deploy with the same stack name.

```bash
# Re-package (picks up any template changes)
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket my-org-cfn-artifacts-us-east-1 \
  --output-template-file rag-pipeline-packaged-stack.json

# Deploy the update
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name rag-dev-pipeline \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      ProjectPrefix=rag-dev \
      EnvironmentTag=Development \
      DeploymentDate=04-22-2026 \
      ... # same parameters as initial deploy
```

### Worked Example — Updating a Single Parameter

```bash
# Enable OpenSearch standby replicas on an existing stack
aws cloudformation update-stack \
  --stack-name rag-dev-pipeline \
  --use-previous-template \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
      ParameterKey=StandbyReplicas,ParameterValue=ENABLED \
      ParameterKey=ProjectPrefix,UsePreviousValue=true \
      ParameterKey=EnvironmentTag,UsePreviousValue=true \
      ParameterKey=DeploymentDate,UsePreviousValue=true \
      ParameterKey=VpcId,UsePreviousValue=true \
      ParameterKey=PrivateSubnetAId,UsePreviousValue=true \
      ParameterKey=PrivateSubnetBId,UsePreviousValue=true \
      ParameterKey=PrivateRouteTableId,UsePreviousValue=true \
      ParameterKey=InternalSGId,UsePreviousValue=true \
      ParameterKey=RdsMultiAZ,UsePreviousValue=true \
      ParameterKey=RdsDeletionProtection,UsePreviousValue=true \
      ParameterKey=RdsMasterUsername,UsePreviousValue=true \
      ParameterKey=RdsKmsKeyArn,UsePreviousValue=true \
      ParameterKey=TenantId,UsePreviousValue=true \
      ParameterKey=ClientId,UsePreviousValue=true \
      ParameterKey=ClientSecretArn,UsePreviousValue=true \
      ParameterKey=SharepointUrl,UsePreviousValue=true \
      ParameterKey=DriveName,UsePreviousValue=true \
      ParameterKey=ImportDocumentsLambdaS3Key,UsePreviousValue=true \
      ParameterKey=CsvCategories,UsePreviousValue=true \
      ParameterKey=SharePointFolderPath,UsePreviousValue=true
```

---

## Step 9 — Tearing Down

Deletion order matters because of cross-stack references and retention policies.

**Important:** Several resources have `DeletionPolicy: RetainExceptOnCreate` or `Snapshot`. This means:
- S3 buckets (except pipeline-artifacts) are retained on delete — you must empty and delete them manually.
- The RDS instance takes a final snapshot before deletion.

```bash
# Delete the pipeline stack
aws cloudformation delete-stack --stack-name rag-dev-pipeline

# Wait for deletion
aws cloudformation wait stack-delete-complete --stack-name rag-dev-pipeline

# Then delete the VPC stack (if you deployed it)
aws cloudformation delete-stack --stack-name rag-vpc-stack
```

### Worked Example — Clean Up Retained Buckets

```bash
# List retained buckets
aws s3 ls | grep rag-dev

# Empty and delete each one
for BUCKET in rag-dev-raw-documents rag-dev-processed-documents \
              rag-dev-embeddings-vectors rag-dev-metadata-index \
              rag-dev-logs-audit; do
  echo "Emptying $BUCKET..."
  aws s3 rm s3://$BUCKET --recursive
  echo "Deleting $BUCKET..."
  aws s3 rb s3://$BUCKET
done

# Delete the SharePoint secret
aws secretsmanager delete-secret \
  --secret-id rag-pipeline/sharepoint-client-secret \
  --force-delete-without-recovery
```

---

## Parameter Reference

| Parameter | Required | Default | Description |
|---|---|---|---|
| `ProjectPrefix` | Yes | — | Lowercase prefix for all resource names (e.g. `rag-dev`). Max 30 chars. |
| `EnvironmentTag` | Yes | — | Tag value: `Production`, `Staging`, or `Development` |
| `DeploymentDate` | Yes | — | `MM-DD-YYYY` format. Baked into the RDS instance identifier. |
| `VpcId` | Yes | — | VPC ID for all resources |
| `PrivateSubnetAId` | Yes | — | Private subnet in AZ-a |
| `PrivateSubnetBId` | Yes | — | Private subnet in AZ-b |
| `PrivateRouteTableId` | Yes | — | Route table for gateway endpoints |
| `InternalSGId` | Yes | — | Security group allowing intra-VPC traffic |
| `StandbyReplicas` | No | `DISABLED` | OpenSearch HA. `ENABLED` for production. |
| `RdsMultiAZ` | No | `false` | RDS Multi-AZ. `true` for production. |
| `RdsDeletionProtection` | No | `false` | Prevent accidental RDS deletion. `true` for production. |
| `RdsMasterUsername` | No | `pgadmin` | PostgreSQL master username |
| `RdsKmsKeyArn` | No | `""` | CMK ARN for RDS + Secrets Manager encryption |
| `TenantId` | Yes | — | Azure AD tenant ID |
| `ClientId` | Yes | — | Azure AD application (client) ID |
| `ClientSecretArn` | Yes | — | Secrets Manager ARN for the Azure AD client secret |
| `SharepointUrl` | Yes | — | SharePoint site URL |
| `DriveName` | Yes | — | SharePoint document library name |
| `ImportDocumentsLambdaS3Key` | Yes | — | S3 key of the Lambda zip in the pipeline artifacts bucket |
| `CsvCategories` | No | `""` | Comma-separated category filter for imports |
| `SharePointFolderPath` | No | `""` | SharePoint folder path filter |

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `CREATE_FAILED` on OpenSearchStack | Collection name already exists in the account | Change `ProjectPrefix` or delete the existing collection |
| `CREATE_FAILED` on RDSStack | DB instance identifier already exists | Change `DeploymentDate` or delete the old instance |
| `CREATE_FAILED` on BedrockAccessStack | Bedrock models not available in region | Deploy in `us-east-1` or `us-west-2` |
| `CREATE_FAILED` on ImportDocumentsStack | Lambda zip not found at S3 key | Verify the zip was uploaded and the `ImportDocumentsLambdaS3Key` matches |
| `CREATE_FAILED` on StorageStack | Bucket name already taken globally | Change `ProjectPrefix` to something unique |
| Stack stuck in `DELETE_FAILED` | Non-empty S3 buckets or ENIs still attached | Empty buckets manually; wait for Lambda ENIs to detach (can take ~40 min) |
| `CAPABILITY_NAMED_IAM` error | Missing `--capabilities` flag | Add `--capabilities CAPABILITY_NAMED_IAM` to the deploy command |
