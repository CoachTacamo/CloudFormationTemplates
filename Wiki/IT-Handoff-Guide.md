# RAG Pipeline — IT Handoff Guide

> **TL;DR:** This stack deploys a serverless RAG (Retrieval-Augmented Generation) pipeline into a VPC.
> Two CLI commands: `package` then `deploy`. That's it.
> Everything below is the detail you need to do it right.

---

## 📋 Table of Contents (Jump Links)

| # | Section | Why You Care |
|---|---------|-------------|
| 1 | [What This Stack Creates](#1--what-this-stack-creates) | Know what lands in your account |
| 2 | [Stack Outputs](#2--stack-outputs) | What you get back after deploy |
| 3 | [Parameters — What to Fill In](#3--parameters--what-to-fill-in) | The inputs you need to gather |
| 4 | [Where to Find Param Values in the Console](#4--where-to-find-param-values-in-the-console) | Click-by-click console directions |
| 5 | [GovCloud Deployer IAM Policy](#5--govcloud-deployer-iam-policy) | Attach this before you deploy |
| 6 | [How to Package & Deploy](#6--how-to-package--deploy) | The two commands |
| 7 | [Worked Examples with Param Overrides](#7--worked-examples-with-param-overrides) | Copy-paste-ready commands |
| 8 | [Updating & Previewing Changes](#8--updating--previewing-changes) | Re-deploy safely |
| 9 | [Teardown](#9--teardown) | Clean removal |
| 10 | [Troubleshooting Cheat Sheet](#10--troubleshooting-cheat-sheet) | When things go sideways |

---

## 1 — What This Stack Creates

The parent stack (`rag-pipeline-orchestrator-stack.json`) deploys **6 nested child stacks**. Here's every resource:

### Storage Stack (S3 Buckets)

| Resource | Name Pattern | Purpose |
|----------|-------------|---------|
| Raw Documents Bucket | `{prefix}-raw-documents` | Incoming document uploads |
| Processed Documents Bucket | `{prefix}-processed-documents` | Parsed/cleaned documents |
| Embeddings Vectors Bucket | `{prefix}-embeddings-vectors` | Stored vector embeddings |
| Metadata Index Bucket | `{prefix}-metadata-index` | Document metadata archive |
| Pipeline Artifacts Bucket | `{prefix}-pipeline-artifacts` | Build/deploy artifacts |
| Logs Audit Bucket | `{prefix}-logs-audit` | Audit and access logs |
| S3 Gateway VPC Endpoint | — | Private S3 access (no NAT needed, free) |

> All buckets have: versioning ON, public access BLOCKED, ABAC enabled, `RetainExceptOnCreate` deletion policy.

### DynamoDB Stack

| Resource | Name Pattern | Purpose |
|----------|-------------|---------|
| Documents Table | `{prefix}-documents` | Tracks document processing status. PK: `documentId` |
| Chunks Table | `{prefix}-chunks` | Chunk-to-document mapping. PK: `documentId`, SK: `chunkId`. TTL enabled. |
| DynamoDB Gateway VPC Endpoint | — | Private DynamoDB access (no NAT needed, free) |

> Both tables: on-demand billing, point-in-time recovery ON, SSE ON, `RetainExceptOnCreate` deletion policy. Documents table has DynamoDB Streams (NEW_AND_OLD_IMAGES).

### OpenSearch Stack

| Resource | Name Pattern | Purpose |
|----------|-------------|---------|
| Vector Search Collection | `{prefix}-vectors` | OpenSearch Serverless VECTORSEARCH collection for embeddings |
| VPC Endpoint | `{prefix}-vectors-vpce` | Private access to the collection |
| Encryption Policy | `{prefix}-vectors-enc` | AWS-owned key encryption |
| Network Policy | `{prefix}-vectors-net` | VPC-only access, no public |
| Data Access Policy | `{prefix}-vectors-access` | IAM root access to indexes and collection |

### Bedrock Access Stack

| Resource | Name Pattern | Purpose |
|----------|-------------|---------|
| IAM Role | `{prefix}-bedrock-access-role` | Execution role for the custom resource Lambda |
| Lambda Function | `{prefix}-bedrock-access` | Custom resource that enables Bedrock model agreements |
| Custom Resource | — | Auto-accepts model access for embedding + generation models on create, removes on delete |

> Default models: `amazon.titan-embed-text-v2:0` (embeddings) and `amazon.nova-pro-v1:0` (generation). Overridable via parameters.

### ImportDocuments Stack (SharePoint Ingestion Lambda)

| Resource | Name Pattern | Purpose |
|----------|-------------|---------|
| IAM Execution Role | `{prefix}-import-documents-role` | Least-privilege role for the Lambda (S3, CloudWatch, VPC, Secrets Manager) |
| Lambda Function | `{prefix}-import-documents` | Python 3.12 function that imports documents from SharePoint into the raw documents bucket |
| CloudWatch Logs VPC Endpoint | — | Interface endpoint for CloudWatch Logs (keeps logging on AWS backbone) |
| Secrets Manager VPC Endpoint | — | Interface endpoint for Secrets Manager (keeps secret retrieval on AWS backbone) |

> The Lambda is deployed into VPC private subnets. It retrieves the Azure AD client secret from Secrets Manager at runtime — the secret value never appears in CloudFormation parameters or the Lambda console. S3 access routes through the existing S3 Gateway Endpoint from the Storage Stack.

---

## 2 — Stack Outputs

After a successful deploy, these values are available in the CloudFormation console under the **Outputs** tab, or via CLI.

| Output Key | What It Is |
|-----------|-----------|
| `VpcId` | VPC the pipeline is deployed into |
| `PrivateSubnetAId` / `PrivateSubnetBId` | The two private subnets used |
| `InternalSGId` | Security group for internal comms |
| `CollectionArn` | OpenSearch Serverless collection ARN |
| `CollectionEndpoint` | OpenSearch Serverless endpoint URL |
| `CollectionId` | OpenSearch Serverless collection ID |
| `DashboardEndpoint` | OpenSearch Dashboards URL |
| `OpenSearchVpcEndpointId` | OpenSearch VPC endpoint ID |
| `DocumentsTableName` / `DocumentsTableArn` | Documents DynamoDB table |
| `DocumentsTableStreamArn` | DynamoDB Stream ARN for the Documents table |
| `ChunksTableName` / `ChunksTableArn` | Chunks DynamoDB table |
| `DynamoDBVpcEndpointId` | DynamoDB gateway endpoint ID |
| `RawDocumentsBucketName` / `RawDocumentsBucketArn` | Raw docs bucket |
| `ProcessedDocumentsBucketName` / `ProcessedDocumentsBucketArn` | Processed docs bucket |
| `EmbeddingsVectorsBucketName` / `EmbeddingsVectorsBucketArn` | Embeddings bucket |
| `MetadataIndexBucketName` / `MetadataIndexBucketArn` | Metadata bucket |
| `PipelineArtifactsBucketName` / `PipelineArtifactsBucketArn` | Artifacts bucket |
| `LogsAuditBucketName` / `LogsAuditBucketArn` | Logs bucket |
| `S3VpcEndpointId` | S3 gateway endpoint ID |
| `BedrockEmbeddingModelId` | Embedding model ID with access enabled |
| `BedrockGenerationModelId` | Generation model ID with access enabled |
| `OpenSearchStackId` / `DynamoDBStackId` / `StorageStackId` | Nested stack IDs |
| `ImportDocumentsFunctionArn` | ImportDocuments Lambda function ARN |
| `ImportDocumentsFunctionName` | ImportDocuments Lambda function name |
| `ImportDocumentsRoleArn` | ImportDocuments IAM execution role ARN |
| `ImportDocumentsCloudWatchLogsVpcEndpointId` | CloudWatch Logs VPC endpoint ID (ImportDocuments stack) |
| `ImportDocumentsSecretsManagerVpcEndpointId` | Secrets Manager VPC endpoint ID (ImportDocuments stack) |
| `ImportDocumentsStackId` | ImportDocuments nested stack ID |

**CLI to dump all outputs:**

```bash
aws cloudformation describe-stacks \
  --stack-name <YOUR_STACK_NAME> \
  --query "Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}" \
  --output table \
  --profile <YOUR_PROFILE>
```

---

## 3 — Parameters — What to Fill In

### Required (no defaults — you must provide these)

| Parameter | Type | Rules | What It Is |
|-----------|------|-------|-----------|
| `VpcId` | `AWS::EC2::VPC::Id` | Must be a valid VPC ID | VPC to deploy into |
| `PrivateSubnetAId` | `AWS::EC2::Subnet::Id` | Must belong to the VPC above | First private subnet |
| `PrivateSubnetBId` | `AWS::EC2::Subnet::Id` | Must belong to the VPC above | Second private subnet (different AZ) |
| `InternalSGId` | `AWS::EC2::SecurityGroup::Id` | Must belong to the VPC above | Security group for internal traffic |
| `PrivateRouteTableId` | `String` | Route table associated with the private subnets | Used to attach gateway endpoints |
| `ProjectPrefix` | `String` | Max 30 chars. Lowercase `a-z`, `0-9`, hyphens only. Must start/end with alphanumeric. | Names everything. **Must be unique in your account.** |
| `EnvironmentTag` | `String` | Free text | Environment label for resource tags (e.g., `Production`, `Development`) |
| `DeploymentDate` | `String` | Format: `MM-DD-YYYY` | Used in the RDS instance identifier |
| `TenantId` | `String` | Azure AD GovCloud tenant GUID | For SharePoint authentication (ImportDocuments) |
| `ClientId` | `String` | Azure AD application GUID | For SharePoint authentication (ImportDocuments) |
| `ClientSecretArn` | `String` | Full Secrets Manager ARN | ARN of the secret containing the Azure AD client secret. **The secret value is never passed as a parameter.** |
| `SharepointUrl` | `String` | Full URL | SharePoint site URL (e.g., `https://contoso.sharepoint.us/sites/documents`) |
| `DriveName` | `String` | Drive/library name | SharePoint document library name (e.g., `Shared Documents`) |
| `ImportDocumentsLambdaS3Key` | `String` | S3 object key | S3 key of the Lambda zip in the pipeline artifacts bucket (e.g., `lambdas/import-documents-lambda.zip`) |

### Optional (have defaults)

| Parameter | Default | Options | What It Does |
|-----------|---------|---------|-------------|
| `StandbyReplicas` | `DISABLED` | `ENABLED` / `DISABLED` | OpenSearch HA replicas. `DISABLED` = half the cost. Use `ENABLED` for production. |
| `RdsDeletionProtection` | `false` | `true` / `false` | RDS deletion protection. Set to `true` for production. |
| `RdsKmsKeyArn` | `""` | KMS key ARN or empty | Optional KMS key for RDS storage encryption. Empty = AWS-managed key. |
| `RdsMasterUsername` | `pgadmin` | Any valid username | Master username for the RDS PostgreSQL instance (NoEcho). |
| `RdsMultiAZ` | `false` | `true` / `false` | Multi-AZ for RDS. Set to `true` for production HA. |
| `CsvCategories` | `""` | Comma-separated | Category filter for ImportDocuments (optional) |
| `SharePointFolderPath` | `""` | Folder path | SharePoint folder path filter for ImportDocuments (optional) |

> **Important:** All 5 networking params (`VpcId`, `PrivateSubnetAId`, `PrivateSubnetBId`, `InternalSGId`, `PrivateRouteTableId`) must reference resources in the **same VPC**. Mismatches = deployment failure.

### Pre-deployment: Create the Client Secret in Secrets Manager

Before deploying, store the Azure AD client secret in Secrets Manager and note the ARN:

```bash
aws secretsmanager create-secret \
  --name "<YOUR_PROJECT_PREFIX>-sp-client-secret" \
  --description "Azure AD client secret for SharePoint ImportDocuments Lambda" \
  --secret-string "<YOUR_ACTUAL_CLIENT_SECRET>" \
  --profile <YOUR_PROFILE>
```

Copy the `ARN` from the output — that's your `ClientSecretArn` parameter value.

### Pre-deployment: Upload the Lambda Zip

```bash
# Create the zip
zip -r import-documents-lambda.zip import_documents.py sharepoint_auth.py sharepoint_graph.py

# Upload to the pipeline artifacts bucket (bucket is created by StorageStack,
# so on first deploy you may need to create it manually or deploy StorageStack first)
aws s3 cp import-documents-lambda.zip \
  s3://<YOUR_PROJECT_PREFIX>-pipeline-artifacts/lambdas/import-documents-lambda.zip \
  --profile <YOUR_PROFILE>
```

---

## 4 — Where to Find Param Values in the Console

Don't have the IDs memorized? Here's where to click.

### VpcId
1. AWS Console → **VPC** → **Your VPCs** (left sidebar)
2. Copy the `vpc-xxxxxxxxx` value from the **VPC ID** column

### PrivateSubnetAId / PrivateSubnetBId
1. AWS Console → **VPC** → **Subnets** (left sidebar)
2. Filter by your VPC ID
3. Pick two subnets in **different Availability Zones**
4. Copy both `subnet-xxxxxxxxx` values

### InternalSGId
1. AWS Console → **VPC** → **Security Groups** (left sidebar, under Security)
2. Filter by your VPC ID
3. Copy the `sg-xxxxxxxxx` value for the internal/pipeline security group

### PrivateRouteTableId
1. AWS Console → **VPC** → **Route Tables** (left sidebar)
2. Filter by your VPC ID
3. Find the route table associated with your private subnets
4. Copy the `rtb-xxxxxxxxx` value

### Or Use the CLI (faster)

```bash
# VPCs
aws ec2 describe-vpcs \
  --query "Vpcs[*].{Id:VpcId,Name:Tags[?Key=='Name']|[0].Value}" \
  --output table --profile <PROFILE>

# Subnets for a VPC
aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=<VPC_ID>" \
  --query "Subnets[*].{Id:SubnetId,AZ:AvailabilityZone,Name:Tags[?Key=='Name']|[0].Value}" \
  --output table --profile <PROFILE>

# Security Groups for a VPC
aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=<VPC_ID>" \
  --query "SecurityGroups[*].{Id:GroupId,Name:GroupName}" \
  --output table --profile <PROFILE>

# Route Tables for a VPC
aws ec2 describe-route-tables \
  --filters "Name=vpc-id,Values=<VPC_ID>" \
  --query "RouteTables[*].{Id:RouteTableId,Name:Tags[?Key=='Name']|[0].Value}" \
  --output table --profile <PROFILE>
```

---

## 5 — GovCloud Deployer IAM Policy

**Before deploying**, attach this policy to the IAM user or role that will run the CloudFormation commands.

> ⚠️ Replace every `xxxxxxxxxxxx` with your **12-digit AWS account ID** before attaching.


```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CloudFormationGetTemplateSummaryUnscoped",
      "Effect": "Allow",
      "Action": [
        "cloudformation:GetTemplateSummary",
        "cloudformation:ValidateTemplate"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudFormationStackManagement",
      "Effect": "Allow",
      "Action": [
        "cloudformation:CreateChangeSet",
        "cloudformation:CreateStack",
        "cloudformation:DeleteChangeSet",
        "cloudformation:DeleteStack",
        "cloudformation:DescribeChangeSet",
        "cloudformation:DescribeStackEvents",
        "cloudformation:DescribeStackResources",
        "cloudformation:DescribeStacks",
        "cloudformation:ExecuteChangeSet",
        "cloudformation:GetTemplate",
        "cloudformation:GetTemplateSummary",
        "cloudformation:ListChangeSets",
        "cloudformation:ListStackResources",
        "cloudformation:UpdateStack"
      ],
      "Resource": [
        "arn:aws-us-gov:cloudformation:us-gov-west-1:xxxxxxxxxxxx:stack/rag-*",
        "arn:aws-us-gov:cloudformation:us-gov-west-1:xxxxxxxxxxxx:stack/rag-*/*"
      ]
    },
    {
      "Sid": "NestedStackTemplateAccess",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": [
        "arn:aws-us-gov:s3:::coachai-ka-cloudformation-test-grounds/*"
      ]
    },
    {
      "Sid": "OpenSearchServerlessManagement",
      "Effect": "Allow",
      "Action": [
        "aoss:BatchGetCollection",
        "aoss:BatchGetVpcEndpoint",
        "aoss:CreateAccessPolicy",
        "aoss:CreateCollection",
        "aoss:CreateSecurityPolicy",
        "aoss:CreateVpcEndpoint",
        "aoss:DeleteAccessPolicy",
        "aoss:DeleteCollection",
        "aoss:DeleteSecurityPolicy",
        "aoss:DeleteVpcEndpoint",
        "aoss:GetAccessPolicy",
        "aoss:GetSecurityPolicy",
        "aoss:ListAccessPolicies",
        "aoss:ListCollections",
        "aoss:ListSecurityPolicies",
        "aoss:ListTagsForResource",
        "aoss:ListVpcEndpoints",
        "aoss:TagResource",
        "aoss:UntagResource",
        "aoss:UpdateAccessPolicy",
        "aoss:UpdateCollection",
        "aoss:UpdateSecurityPolicy",
        "aoss:UpdateVpcEndpoint"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-gov-west-1"
        }
      }
    },
    {
      "Sid": "S3BucketManagement",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:DeleteBucket",
        "s3:DeleteBucketPolicy",
        "s3:GetBucketAcl",
        "s3:GetBucketLocation",
        "s3:GetBucketPolicy",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketTagging",
        "s3:GetBucketVersioning",
        "s3:GetEncryptionConfiguration",
        "s3:GetLifecycleConfiguration",
        "s3:ListBucket",
        "s3:PutBucketPolicy",
        "s3:PutBucketPublicAccessBlock",
        "s3:PutBucketTagging",
        "s3:PutBucketVersioning",
        "s3:PutEncryptionConfiguration",
        "s3:PutLifecycleConfiguration"
      ],
      "Resource": [
        "arn:aws-us-gov:s3:::*-embeddings-vectors",
        "arn:aws-us-gov:s3:::*-logs-audit",
        "arn:aws-us-gov:s3:::*-metadata-index",
        "arn:aws-us-gov:s3:::*-pipeline-artifacts",
        "arn:aws-us-gov:s3:::*-processed-documents",
        "arn:aws-us-gov:s3:::*-raw-documents"
      ]
    },
    {
      "Sid": "EC2VpcManagement",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateVpc",
        "ec2:DeleteVpc",
        "ec2:DescribeVpcs",
        "ec2:DescribeVpcAttribute",
        "ec2:ModifyVpcAttribute"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-gov-west-1"
        }
      }
    },
    {
      "Sid": "EC2SubnetManagement",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateSubnet",
        "ec2:DeleteSubnet",
        "ec2:DescribeSubnets",
        "ec2:DescribeAvailabilityZones"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-gov-west-1"
        }
      }
    },
    {
      "Sid": "EC2RouteTableManagement",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateRouteTable",
        "ec2:DeleteRouteTable",
        "ec2:DescribeRouteTables",
        "ec2:CreateRoute",
        "ec2:DeleteRoute",
        "ec2:AssociateRouteTable",
        "ec2:DisassociateRouteTable"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-gov-west-1"
        }
      }
    },
    {
      "Sid": "EC2VpcEndpointManagement",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateVpcEndpoint",
        "ec2:DeleteVpcEndpoints",
        "ec2:DescribeVpcEndpoints",
        "ec2:ModifyVpcEndpoint"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-gov-west-1"
        }
      }
    },
    {
      "Sid": "EC2TaggingForVpcResources",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateTags",
        "ec2:DeleteTags"
      ],
      "Resource": [
        "arn:aws-us-gov:ec2:us-gov-west-1:xxxxxxxxxxxx:vpc/*",
        "arn:aws-us-gov:ec2:us-gov-west-1:xxxxxxxxxxxx:subnet/*",
        "arn:aws-us-gov:ec2:us-gov-west-1:xxxxxxxxxxxx:route-table/*",
        "arn:aws-us-gov:ec2:us-gov-west-1:xxxxxxxxxxxx:vpc-endpoint/*"
      ]
    },
    {
      "Sid": "EC2SecurityGroupForOpenSearch",
      "Effect": "Allow",
      "Action": [
        "ec2:AuthorizeSecurityGroupEgress",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:CreateSecurityGroup",
        "ec2:CreateTags",
        "ec2:DeleteSecurityGroup",
        "ec2:DeleteTags",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeVpcs",
        "ec2:RevokeSecurityGroupEgress",
        "ec2:RevokeSecurityGroupIngress"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-gov-west-1"
        }
      }
    },
    {
      "Sid": "EC2DescribeNetworkInterfaces",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeNetworkInterfaces"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-gov-west-1"
        }
      }
    },
    {
      "Sid": "IAMRoleManagementForBedrockAccess",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:GetRole",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:GetRolePolicy",
        "iam:PassRole",
        "iam:TagRole",
        "iam:UntagRole"
      ],
      "Resource": [
        "arn:aws-us-gov:iam::xxxxxxxxxxxx:role/rag-*-bedrock-access-role"
      ]
    },
    {
      "Sid": "LambdaManagementForBedrockAccess",
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction",
        "lambda:DeleteFunction",
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration",
        "lambda:InvokeFunction",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "lambda:TagResource",
        "lambda:UntagResource"
      ],
      "Resource": [
        "arn:aws-us-gov:lambda:us-gov-west-1:xxxxxxxxxxxx:function:rag-*-bedrock-access"
      ]
    },
    {
      "Sid": "CloudWatchLogsForBedrockAccess",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:DeleteLogGroup",
        "logs:DescribeLogGroups"
      ],
      "Resource": [
        "arn:aws-us-gov:logs:us-gov-west-1:xxxxxxxxxxxx:log-group:/aws/lambda/rag-*-bedrock-access:*"
      ]
    }
  ]
}
```

**How to attach it:**
1. AWS Console → **IAM** → **Users** (or **Roles**)
2. Select the deployer identity → **Permissions** tab → **Add permissions** → **Create inline policy**
3. Switch to the **JSON** tab, paste the policy above (with your account ID), save

---

## 6 — How to Package & Deploy

### Prerequisites Checklist

- [ ] AWS CLI v2 installed (`aws --version`)
- [ ] CLI profile configured with deployer permissions (Section 5)
- [ ] An S3 bucket for CloudFormation artifacts (any bucket you have write access to)
- [ ] VPC networking values gathered (Section 4)

### Step 1 — Package

This uploads the nested child templates to S3 and produces a single deployable file:

```bash
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket <YOUR_ARTIFACT_BUCKET> \
  --output-template-file rag-pipeline-packaged-stack.json \
  --profile <YOUR_PROFILE>
```

**What happens:** The CLI finds every `TemplateURL` pointing to a local file, uploads that file to your S3 bucket, and rewrites the URL to the S3 location. The output file is what you deploy.

### Step 2 — Deploy

```bash
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name <YOUR_STACK_NAME> \
  --parameter-overrides \
    VpcId=<VPC_ID> \
    PrivateSubnetAId=<SUBNET_A_ID> \
    PrivateSubnetBId=<SUBNET_B_ID> \
    InternalSGId=<SG_ID> \
    PrivateRouteTableId=<RTB_ID> \
    ProjectPrefix=<YOUR_PREFIX> \
    EnvironmentTag=<YOUR_ENVIRONMENT> \
    DeploymentDate=<MM-DD-YYYY> \
    TenantId=<AZURE_AD_TENANT_ID> \
    ClientId=<AZURE_AD_CLIENT_ID> \
    ClientSecretArn=<SECRETS_MANAGER_ARN> \
    SharepointUrl=<SHAREPOINT_SITE_URL> \
    DriveName=<SHAREPOINT_DRIVE_NAME> \
    ImportDocumentsLambdaS3Key=<LAMBDA_ZIP_S3_KEY> \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile <YOUR_PROFILE>
```

> `--capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM` is **required** because nested stacks create IAM roles (Bedrock Access stack and ImportDocuments stack).

---

## 7 — Worked Examples with Param Overrides

### Example A — Dev Environment (cost-optimized, standby replicas OFF)

```bash
# Package
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket my-cfn-artifacts \
  --output-template-file rag-pipeline-packaged-stack.json \
  --profile govcloud-deployer

# Deploy
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name rag-dev-pipeline \
  --parameter-overrides \
    VpcId=vpc-0abc1234def56789a \
    PrivateSubnetAId=subnet-0aaa1111bbbb2222c \
    PrivateSubnetBId=subnet-0ddd3333eeee4444f \
    InternalSGId=sg-0fff5555aaaa6666b \
    PrivateRouteTableId=rtb-0ccc7777dddd8888e \
    ProjectPrefix=rag-dev \
    EnvironmentTag=Development \
    DeploymentDate=04-15-2026 \
    TenantId=a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
    ClientId=12345678-abcd-ef01-2345-6789abcdef01 \
    ClientSecretArn=arn:aws-us-gov:secretsmanager:us-gov-west-1:111122223333:secret:rag-dev-sp-client-secret-AbCdEf \
    SharepointUrl=https://contoso.sharepoint.us/sites/documents \
    DriveName=Shared\ Documents \
    ImportDocumentsLambdaS3Key=lambdas/import-documents-lambda.zip \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile govcloud-deployer
```

### Example B — Production (standby replicas ON, RDS HA, deletion protection)

```bash
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name rag-prod-pipeline \
  --parameter-overrides \
    VpcId=vpc-0abc1234def56789a \
    PrivateSubnetAId=subnet-0aaa1111bbbb2222c \
    PrivateSubnetBId=subnet-0ddd3333eeee4444f \
    InternalSGId=sg-0fff5555aaaa6666b \
    PrivateRouteTableId=rtb-0ccc7777dddd8888e \
    ProjectPrefix=rag-prod \
    EnvironmentTag=Production \
    DeploymentDate=04-15-2026 \
    TenantId=a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
    ClientId=12345678-abcd-ef01-2345-6789abcdef01 \
    ClientSecretArn=arn:aws-us-gov:secretsmanager:us-gov-west-1:111122223333:secret:rag-prod-sp-client-secret-XyZwVu \
    SharepointUrl=https://contoso.sharepoint.us/sites/documents \
    DriveName=Shared\ Documents \
    ImportDocumentsLambdaS3Key=lambdas/import-documents-lambda.zip \
    StandbyReplicas=ENABLED \
    RdsMultiAZ=true \
    RdsDeletionProtection=true \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile govcloud-deployer
```

### Example C — With Category and Folder Filters

```bash
# Same as Example A, but only import documents from a specific folder and categories
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name rag-dev-pipeline \
  --parameter-overrides \
    VpcId=vpc-0abc1234def56789a \
    PrivateSubnetAId=subnet-0aaa1111bbbb2222c \
    PrivateSubnetBId=subnet-0ddd3333eeee4444f \
    InternalSGId=sg-0fff5555aaaa6666b \
    PrivateRouteTableId=rtb-0ccc7777dddd8888e \
    ProjectPrefix=rag-dev \
    EnvironmentTag=Development \
    DeploymentDate=04-15-2026 \
    TenantId=a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
    ClientId=12345678-abcd-ef01-2345-6789abcdef01 \
    ClientSecretArn=arn:aws-us-gov:secretsmanager:us-gov-west-1:111122223333:secret:rag-dev-sp-client-secret-AbCdEf \
    SharepointUrl=https://contoso.sharepoint.us/sites/documents \
    DriveName=Shared\ Documents \
    ImportDocumentsLambdaS3Key=lambdas/import-documents-lambda.zip \
    CsvCategories=Policy,Procedure,Guide \
    SharePointFolderPath=/sites/documents/Policies \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile govcloud-deployer
```

### Example D — Using the Included VPC Stack First (no existing VPC)

```bash
# 1. Deploy the VPC stack
aws cloudformation deploy \
  --template-file "Special Stacks/vpc-stack.json" \
  --stack-name rag-eval-vpc \
  --parameter-overrides \
    EnvironmentName=rag-eval \
    VpcCidr=10.2.0.0/16 \
    SubnetACidr=10.2.1.0/24 \
    SubnetBCidr=10.2.2.0/24 \
  --profile govcloud-deployer

# 2. Grab the outputs
aws cloudformation describe-stacks \
  --stack-name rag-eval-vpc \
  --query "Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}" \
  --output table \
  --profile govcloud-deployer

# 3. Use those output values in the pipeline deploy
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket my-cfn-artifacts \
  --output-template-file rag-pipeline-packaged-stack.json \
  --profile govcloud-deployer

aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name rag-eval-pipeline \
  --parameter-overrides \
    VpcId=<VpcId from step 2> \
    PrivateSubnetAId=<PrivateSubnetAId from step 2> \
    PrivateSubnetBId=<PrivateSubnetBId from step 2> \
    InternalSGId=<InternalSecurityGroupId from step 2> \
    PrivateRouteTableId=<PrivateRouteTableId from step 2> \
    ProjectPrefix=rag-eval \
    EnvironmentTag=Evaluation \
    DeploymentDate=04-15-2026 \
    TenantId=<YOUR_AZURE_AD_TENANT_ID> \
    ClientId=<YOUR_AZURE_AD_CLIENT_ID> \
    ClientSecretArn=<YOUR_SECRETS_MANAGER_ARN> \
    SharepointUrl=<YOUR_SHAREPOINT_SITE_URL> \
    DriveName=<YOUR_SHAREPOINT_DRIVE_NAME> \
    ImportDocumentsLambdaS3Key=lambdas/import-documents-lambda.zip \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile govcloud-deployer
```

---

## 8 — Updating & Previewing Changes

### Re-deploy After Template Changes

Same two commands. CloudFormation diffs automatically.

```bash
# Re-package (always do this first)
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket <YOUR_ARTIFACT_BUCKET> \
  --output-template-file rag-pipeline-packaged-stack.json \
  --profile <YOUR_PROFILE>

# Re-deploy (same command as initial deploy)
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name <YOUR_STACK_NAME> \
  --parameter-overrides \
    VpcId=<VPC_ID> \
    PrivateSubnetAId=<SUBNET_A_ID> \
    PrivateSubnetBId=<SUBNET_B_ID> \
    InternalSGId=<SG_ID> \
    PrivateRouteTableId=<RTB_ID> \
    ProjectPrefix=<YOUR_PREFIX> \
    EnvironmentTag=<YOUR_ENVIRONMENT> \
    DeploymentDate=<MM-DD-YYYY> \
    TenantId=<AZURE_AD_TENANT_ID> \
    ClientId=<AZURE_AD_CLIENT_ID> \
    ClientSecretArn=<SECRETS_MANAGER_ARN> \
    SharepointUrl=<SHAREPOINT_SITE_URL> \
    DriveName=<SHAREPOINT_DRIVE_NAME> \
    ImportDocumentsLambdaS3Key=<LAMBDA_ZIP_S3_KEY> \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile <YOUR_PROFILE>
```

If nothing changed: `No changes to deploy. Stack <name> is up to date.`

### Preview Without Applying (Dry Run)

Add `--no-execute-changeset` to the deploy command:

```bash
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name <YOUR_STACK_NAME> \
  --parameter-overrides \
    VpcId=<VPC_ID> \
    PrivateSubnetAId=<SUBNET_A_ID> \
    PrivateSubnetBId=<SUBNET_B_ID> \
    InternalSGId=<SG_ID> \
    PrivateRouteTableId=<RTB_ID> \
    ProjectPrefix=<YOUR_PREFIX> \
    EnvironmentTag=<YOUR_ENVIRONMENT> \
    DeploymentDate=<MM-DD-YYYY> \
    TenantId=<AZURE_AD_TENANT_ID> \
    ClientId=<AZURE_AD_CLIENT_ID> \
    ClientSecretArn=<SECRETS_MANAGER_ARN> \
    SharepointUrl=<SHAREPOINT_SITE_URL> \
    DriveName=<SHAREPOINT_DRIVE_NAME> \
    ImportDocumentsLambdaS3Key=<LAMBDA_ZIP_S3_KEY> \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile <YOUR_PROFILE> \
  --no-execute-changeset
```

Review the changeset, then execute when ready:

```bash
aws cloudformation execute-change-set \
  --stack-name <YOUR_STACK_NAME> \
  --change-set-name <CHANGESET_NAME_FROM_OUTPUT> \
  --profile <YOUR_PROFILE>
```

---

## 9 — Teardown

### Delete the Pipeline Stack

```bash
aws cloudformation delete-stack \
  --stack-name <YOUR_STACK_NAME> \
  --profile <YOUR_PROFILE>
```

**Heads up:** S3 buckets and DynamoDB tables use `RetainExceptOnCreate`. If they were successfully created, they survive stack deletion. Clean them up manually:

```bash
# Find retained buckets
aws s3 ls | grep <YOUR_PROJECT_PREFIX>

# Empty and delete each one
aws s3 rb s3://<BUCKET_NAME> --force --profile <YOUR_PROFILE>
```

### Delete the VPC Stack (if you deployed one)

```bash
aws cloudformation delete-stack \
  --stack-name <YOUR_VPC_STACK_NAME> \
  --profile <YOUR_PROFILE>
```

### Verify It's Gone

```bash
aws cloudformation describe-stacks \
  --stack-name <YOUR_STACK_NAME> \
  --profile <YOUR_PROFILE>
```

`DELETE_COMPLETE` or "does not exist" = success.

---

## 10 — Troubleshooting Cheat Sheet

| What You See | Why | Fix |
|-------------|-----|-----|
| `S3 bucket already exists` | Another stack/account owns a bucket with that name | Change `ProjectPrefix` to something unique |
| `Resource limit exceeded` (OpenSearch) | Account-level collection limit hit | Request a quota increase or delete unused collections |
| `CREATE_FAILED` on VPC endpoint | SG or subnet doesn't belong to the specified VPC | Verify all networking params are from the same VPC |
| `Parameter validation failed` on `ProjectPrefix` | Doesn't match `^[a-z0-9][a-z0-9\-]*[a-z0-9]$` | Lowercase, numbers, hyphens only. Start/end alphanumeric. Max 30 chars. |
| `CAPABILITY_IAM` error | Missing `--capabilities` flag | Add `--capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM` |
| Stack stuck in `ROLLBACK_IN_PROGRESS` | A resource failed to create | Check events: `aws cloudformation describe-stack-events --stack-name <NAME>` |

### Quick Diagnostic Commands

```bash
# Stack status
aws cloudformation describe-stacks \
  --stack-name <NAME> \
  --query "Stacks[0].{Status:StackStatus,Reason:StackStatusReason}" \
  --output table --profile <PROFILE>

# Failed resources only
aws cloudformation describe-stack-events \
  --stack-name <NAME> \
  --query "StackEvents[?ResourceStatus=='CREATE_FAILED' || ResourceStatus=='UPDATE_FAILED'].{Resource:LogicalResourceId,Reason:ResourceStatusReason}" \
  --output table --profile <PROFILE>
```
