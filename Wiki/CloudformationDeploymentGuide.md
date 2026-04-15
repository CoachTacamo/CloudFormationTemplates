# RAG Pipeline — CloudFormation Deployment Guide

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Stack Architecture](#2-stack-architecture)
3. [Deployer IAM Policy](#3-deployer-iam-policy)
4. [Deploy the VPC Stack (Optional)](#4-deploy-the-vpc-stack-optional)
5. [Gather Networking Parameters](#5-gather-networking-parameters)
6. [Deploy the RAG Pipeline](#6-deploy-the-rag-pipeline)
7. [Deploying Updates](#7-deploying-updates)
8. [Previewing Changes Before Deploying](#8-previewing-changes-before-deploying)
9. [Monitoring and Troubleshooting](#9-monitoring-and-troubleshooting)
10. [Teardown](#10-teardown)

---

## 1. Prerequisites

- AWS CLI v2 installed and configured
- An AWS CLI profile with permissions to deploy (see [Deployer IAM Policy](#3-deployer-iam-policy))
- An S3 bucket for storing packaged CloudFormation artifacts (e.g., `my-cfn-artifacts-bucket`)
- A VPC with two private subnets, a security group, and a route table — either pre-existing or created via the included VPC stack

---

## 2. Stack Architecture

The deployment uses a nested stack pattern. The orchestrator is the parent stack and it references child stacks:

```
rag-pipeline-orchestrator-stack.json        (parent)
  ├── storage-stack.json                    (S3 buckets + S3 gateway endpoint)
  ├── dynamodb-stack.json                   (DynamoDB tables + DynamoDB gateway endpoint)
  ├── opensearch-stack.json                 (OpenSearch Serverless collection + VPC endpoint)
  ├── rds-stack.json                        (PostgreSQL RDS instance)
  ├── bedrock-access-stack.json             (Bedrock model access custom resource)
  └── import-documents-stack.json           (ImportDocuments Lambda + VPC endpoints)
```

The `aws cloudformation package` command uploads the child templates to S3 and rewrites the local `TemplateURL` references to S3 URLs, producing a deployment-ready `rag-pipeline-packaged-stack.json`.

### What Gets Created

| Nested Stack | Resources |
|---|---|
| storage-stack | 6 S3 buckets: raw-documents, processed-documents, embeddings-vectors, metadata-index, pipeline-artifacts, logs-audit; S3 gateway VPC endpoint |
| dynamodb-stack | Documents table, Chunks table, DynamoDB gateway VPC endpoint |
| opensearch-stack | OpenSearch Serverless vector search collection, VPC endpoint, encryption/network/data-access policies |
| rds-stack | PostgreSQL RDS instance, DB subnet group, security group, Secrets Manager secret for master credentials |
| bedrock-access-stack | IAM role, Lambda function, custom resource for Bedrock model access agreements |
| import-documents-stack | ImportDocuments Lambda (Python 3.12), IAM execution role, CloudWatch Logs VPC endpoint, Secrets Manager VPC endpoint |

---

## 3. Deployer IAM Policy

Before deploying, attach the appropriate deployer policy to your IAM user or role:

| Region Type | Policy File |
|---|---|
| Commercial (e.g., us-east-1) | `Policies/rag-pipeline-deployer-policy.json` |
| GovCloud (e.g., us-gov-west-1) | `Policies/rag-pipeline-deployer-policy-govcloud.json` |

The GovCloud policy is scoped to `us-gov-west-1` and uses `arn:aws-us-gov` resource ARNs. Update the account ID placeholder (`xxxxxxxxxxxx`) in the GovCloud policy before attaching it.

The policies cover: CloudFormation stack management, S3 bucket operations, OpenSearch Serverless, EC2 networking (VPC, subnets, route tables, endpoints, security groups), and DynamoDB table management.

---

## 4. Deploy the VPC Stack (Optional)

> Skip this section if your account already has a VPC with private subnets. Gather the existing IDs and jump to [Gather Networking Parameters](#5-gather-networking-parameters).

The standalone VPC stack at `Special Stacks/vpc-stack.json` creates an isolated private network suitable for the pipeline.

### VPC Stack Parameters

| Parameter | Default | Description |
|---|---|---|
| `EnvironmentName` | `rag-dev` | Prefix for resource names and CloudFormation export names |
| `VpcCidr` | `10.0.0.0/16` | CIDR block for the VPC |
| `SubnetACidr` | `10.0.1.0/24` | CIDR block for private subnet A |
| `SubnetBCidr` | `10.0.2.0/24` | CIDR block for private subnet B |

All parameters have defaults, so a zero-override deploy works for quick dev environments.

### What the VPC Stack Creates

- VPC with DNS support and DNS hostnames enabled
- Two private subnets across two AZs (no public IP assignment)
- A private route table with both subnets associated
- An S3 gateway endpoint (free, enables private S3 access without NAT)
- An internal security group allowing TCP/UDP/ICMP within the VPC CIDR only

### Deploy with Defaults

```bash
aws cloudformation deploy \
  --template-file "Special Stacks/vpc-stack.json" \
  --stack-name rag-dev-vpc \
  --profile <YOUR_PROFILE>
```

### Deploy with Overrides

```bash
aws cloudformation deploy \
  --template-file "Special Stacks/vpc-stack.json" \
  --stack-name my-rag-vpc \
  --parameter-overrides \
    EnvironmentName=my-rag \
    VpcCidr=10.1.0.0/16 \
    SubnetACidr=10.1.1.0/24 \
    SubnetBCidr=10.1.2.0/24 \
  --profile <YOUR_PROFILE>
```

### VPC Stack Exports

After deployment, the stack exports these values (prefixed with the `EnvironmentName` value) for reference:

| Export Name | Value |
|---|---|
| `{EnvironmentName}-VpcId` | VPC ID |
| `{EnvironmentName}-PrivateSubnetAId` | Private Subnet A ID |
| `{EnvironmentName}-PrivateSubnetBId` | Private Subnet B ID |
| `{EnvironmentName}-InternalSGId` | Internal security group ID |
| `{EnvironmentName}-PrivateRouteTableId` | Private route table ID |

Verify exports after deployment:

```bash
aws cloudformation list-exports \
  --query "Exports[?starts_with(Name, '<YOUR_ENVIRONMENT_NAME>')]" \
  --output table \
  --profile <YOUR_PROFILE>
```

---

## 5. Gather Networking Parameters

The orchestrator stack requires networking inputs so it can deploy into any VPC. Gather these values before proceeding.

### Orchestrator Stack Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `VpcId` | `AWS::EC2::VPC::Id` | Yes | — | VPC where pipeline resources will be deployed |
| `PrivateSubnetAId` | `AWS::EC2::Subnet::Id` | Yes | — | First private subnet |
| `PrivateSubnetBId` | `AWS::EC2::Subnet::Id` | Yes | — | Second private subnet |
| `InternalSGId` | `AWS::EC2::SecurityGroup::Id` | Yes | — | Security group for internal pipeline communication |
| `PrivateRouteTableId` | `String` | Yes | — | Route table ID for the private subnets (used for gateway endpoints) |
| `ProjectPrefix` | `String` | Yes | — | Short prefix for resource names (e.g., `rag-dev`). Max 30 chars, lowercase alphanumeric and hyphens only. |
| `EnvironmentTag` | `String` | Yes | — | Environment tag value (e.g., `Production`, `Staging`, `Development`) |
| `DeploymentDate` | `String` | Yes | — | Deployment date in `MM-DD-YYYY` format (e.g., `07-15-2026`). Used in the RDS instance identifier. |
| `TenantId` | `String` | Yes | — | Azure AD tenant ID for SharePoint authentication (ImportDocuments) |
| `ClientId` | `String` | Yes | — | Azure AD client (application) ID for SharePoint authentication (ImportDocuments) |
| `ClientSecretArn` | `String` | Yes | — | ARN of the Secrets Manager secret containing the Azure AD client secret (ImportDocuments) |
| `SharepointUrl` | `String` | Yes | — | SharePoint site URL (ImportDocuments) |
| `DriveName` | `String` | Yes | — | SharePoint document library (drive) name (ImportDocuments) |
| `ImportDocumentsLambdaS3Key` | `String` | Yes | — | S3 key of the ImportDocuments Lambda zip in the pipeline artifacts bucket |
| `StandbyReplicas` | `String` | No | `DISABLED` | OpenSearch standby replicas. Set to `ENABLED` for production HA. `DISABLED` cuts cost in half for dev/test. |
| `RdsDeletionProtection` | `String` | No | `false` | Enable RDS deletion protection. Set to `true` for production. |
| `RdsKmsKeyArn` | `String` | No | `""` | Optional KMS key ARN for RDS storage and Secrets Manager encryption. Leave empty for AWS-managed key. |
| `RdsMasterUsername` | `String` | No | `pgadmin` | Master username for the RDS PostgreSQL instance (NoEcho). |
| `RdsMultiAZ` | `String` | No | `false` | Enable Multi-AZ for RDS. Set to `true` for production. |
| `CsvCategories` | `String` | No | `""` | Comma-separated category filter for ImportDocuments (optional) |
| `SharePointFolderPath` | `String` | No | `""` | SharePoint folder path filter for ImportDocuments (optional) |

### Look Up Values from Your Account

```bash
# List VPCs
aws ec2 describe-vpcs \
  --query "Vpcs[*].{Id:VpcId,Name:Tags[?Key=='Name']|[0].Value}" \
  --output table \
  --profile <YOUR_PROFILE>

# List subnets for a specific VPC
aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=<YOUR_VPC_ID>" \
  --query "Subnets[*].{Id:SubnetId,AZ:AvailabilityZone,Name:Tags[?Key=='Name']|[0].Value}" \
  --output table \
  --profile <YOUR_PROFILE>

# List security groups for a specific VPC
aws ec2 describe-security-groups \
  --filters "Name=vpc-id,Values=<YOUR_VPC_ID>" \
  --query "SecurityGroups[*].{Id:GroupId,Name:GroupName}" \
  --output table \
  --profile <YOUR_PROFILE>

# List route tables for a specific VPC
aws ec2 describe-route-tables \
  --filters "Name=vpc-id,Values=<YOUR_VPC_ID>" \
  --query "RouteTables[*].{Id:RouteTableId,Name:Tags[?Key=='Name']|[0].Value}" \
  --output table \
  --profile <YOUR_PROFILE>
```

---

## 6. Deploy the RAG Pipeline

Deployment is a two-step process: package, then deploy.

### Step 1 — Package the Template

This uploads nested child templates to S3 and produces a deployment-ready packaged template:

```bash
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket <YOUR_ARTIFACT_BUCKET> \
  --output-template-file rag-pipeline-packaged-stack.json \
  --profile <YOUR_PROFILE>
```

```bash
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket prototype-rag-cfn-artifacts-bucket \
  --output-template-file rag-pipeline-packaged-stack.json \
  --profile CloudAdmin
```

### Step 2 — Deploy the Packaged Template

```bash
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name <YOUR_STACK_NAME> \
  --parameter-overrides \
    VpcId=<YOUR_VPC_ID> \
    PrivateSubnetAId=<YOUR_PRIVATE_SUBNET_A_ID> \
    PrivateSubnetBId=<YOUR_PRIVATE_SUBNET_B_ID> \
    InternalSGId=<YOUR_SECURITY_GROUP_ID> \
    PrivateRouteTableId=<YOUR_ROUTE_TABLE_ID> \
    ProjectPrefix=<YOUR_PROJECT_PREFIX> \
    EnvironmentTag=<YOUR_ENVIRONMENT> \
    DeploymentDate=<MM-DD-YYYY> \
    TenantId=<YOUR_AZURE_AD_TENANT_ID> \
    ClientId=<YOUR_AZURE_AD_CLIENT_ID> \
    ClientSecretArn=<YOUR_SECRETS_MANAGER_ARN> \
    SharepointUrl=<YOUR_SHAREPOINT_SITE_URL> \
    DriveName=<YOUR_SHAREPOINT_DRIVE_NAME> \
    ImportDocumentsLambdaS3Key=<YOUR_LAMBDA_ZIP_S3_KEY> \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile <YOUR_PROFILE>
```

#### Preparing the ImportDocuments Lambda Zip

Before deploying, upload the Lambda deployment package to the pipeline artifacts bucket:

```bash
# Create the zip (from the project root containing import_documents.py, sharepoint_auth.py, etc.)
zip -r import-documents-lambda.zip import_documents.py sharepoint_auth.py sharepoint_graph.py

# Upload to the pipeline artifacts bucket
aws s3 cp import-documents-lambda.zip \
  s3://<YOUR_PROJECT_PREFIX>-pipeline-artifacts/lambdas/import-documents-lambda.zip \
  --profile <YOUR_PROFILE>
```

Then use `ImportDocumentsLambdaS3Key=lambdas/import-documents-lambda.zip` in the deploy command.

#### Concrete Example (GovCloud)

```bash
# Package
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket prototype-rag-cfn-artifacts-bucket \
  --output-template-file rag-pipeline-packaged-stack.json \
  --profile CloudAdmin

# Deploy
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name prototype-rag-stack \
  --parameter-overrides \
    VpcId=vpc-0caf0e93fb5f855ac \
    PrivateSubnetAId=subnet-03ff2ce7802a207c6 \
    PrivateSubnetBId=subnet-0499da654af71ff66 \
    InternalSGId=sg-036ab67eaf04608ba \
    PrivateRouteTableId=rtb-01dfd50f0fc9add70 \
    ProjectPrefix=prototype-rag \
    EnvironmentTag=Development \
    DeploymentDate=04-15-2026 \
    TenantId=a1b2c3d4-e5f6-7890-abcd-ef1234567890 \
    ClientId=12345678-abcd-ef01-2345-6789abcdef01 \
    ClientSecretArn=arn:aws-us-gov:secretsmanager:us-gov-west-1:123456789012:secret:prototype-rag-sp-client-secret-AbCdEf \
    SharepointUrl=https://contoso.sharepoint.us/sites/documents \
    DriveName=Shared\ Documents \
    ImportDocumentsLambdaS3Key=lambdas/import-documents-lambda.zip \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile CloudAdmin
```

To also enable OpenSearch standby replicas (production), add `StandbyReplicas=ENABLED` to the `--parameter-overrides`.

To filter ImportDocuments to a specific SharePoint folder or categories, add:
```
    CsvCategories=Policy,Procedure \
    SharePointFolderPath=/sites/documents/Policies \
```

### Notes

- `--capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM` is required because nested stacks may create IAM resources.
- `ProjectPrefix` is used to name all child resources (S3 buckets, DynamoDB tables, OpenSearch collection). Choose a prefix that is unique within your account to avoid naming collisions.
- The `ProjectPrefix` must match the pattern `^[a-z0-9][a-z0-9\-]*[a-z0-9]$` and be at most 30 characters.

---

## 7. Deploying Updates

When you modify any template (parent or nested), re-run both steps. CloudFormation automatically creates a change set, diffs it against the running stack, and applies only the differences.

### Step 1 — Re-package

```bash
aws cloudformation package \
  --template-file rag-pipeline-orchestrator-stack.json \
  --s3-bucket <YOUR_ARTIFACT_BUCKET> \
  --output-template-file rag-pipeline-packaged-stack.json \
  --profile <YOUR_PROFILE>
```

### Step 2 — Re-deploy

```bash
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name <YOUR_STACK_NAME> \
  --parameter-overrides \
    VpcId=<YOUR_VPC_ID> \
    PrivateSubnetAId=<YOUR_PRIVATE_SUBNET_A_ID> \
    PrivateSubnetBId=<YOUR_PRIVATE_SUBNET_B_ID> \
    InternalSGId=<YOUR_SECURITY_GROUP_ID> \
    PrivateRouteTableId=<YOUR_ROUTE_TABLE_ID> \
    ProjectPrefix=<YOUR_PROJECT_PREFIX> \
    EnvironmentTag=<YOUR_ENVIRONMENT> \
    DeploymentDate=<MM-DD-YYYY> \
    TenantId=<YOUR_AZURE_AD_TENANT_ID> \
    ClientId=<YOUR_AZURE_AD_CLIENT_ID> \
    ClientSecretArn=<YOUR_SECRETS_MANAGER_ARN> \
    SharepointUrl=<YOUR_SHAREPOINT_SITE_URL> \
    DriveName=<YOUR_SHAREPOINT_DRIVE_NAME> \
    ImportDocumentsLambdaS3Key=<YOUR_LAMBDA_ZIP_S3_KEY> \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile <YOUR_PROFILE>
```

If nothing changed, you'll see:

```
No changes to deploy. Stack <YOUR_STACK_NAME> is up to date.
```

---

## 8. Previewing Changes Before Deploying

To review what CloudFormation will change without actually applying it, add `--no-execute-changeset`:

```bash
aws cloudformation deploy \
  --template-file rag-pipeline-packaged-stack.json \
  --stack-name <YOUR_STACK_NAME> \
  --parameter-overrides \
    VpcId=<YOUR_VPC_ID> \
    PrivateSubnetAId=<YOUR_PRIVATE_SUBNET_A_ID> \
    PrivateSubnetBId=<YOUR_PRIVATE_SUBNET_B_ID> \
    InternalSGId=<YOUR_SECURITY_GROUP_ID> \
    PrivateRouteTableId=<YOUR_ROUTE_TABLE_ID> \
    ProjectPrefix=<YOUR_PROJECT_PREFIX> \
    EnvironmentTag=<YOUR_ENVIRONMENT> \
    DeploymentDate=<MM-DD-YYYY> \
    TenantId=<YOUR_AZURE_AD_TENANT_ID> \
    ClientId=<YOUR_AZURE_AD_CLIENT_ID> \
    ClientSecretArn=<YOUR_SECRETS_MANAGER_ARN> \
    SharepointUrl=<YOUR_SHAREPOINT_SITE_URL> \
    DriveName=<YOUR_SHAREPOINT_DRIVE_NAME> \
    ImportDocumentsLambdaS3Key=<YOUR_LAMBDA_ZIP_S3_KEY> \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --profile <YOUR_PROFILE> \
  --no-execute-changeset
```

This creates the change set without executing it. Review it in the AWS Console or via CLI:

```bash
# Describe the change set
aws cloudformation describe-change-set \
  --stack-name <YOUR_STACK_NAME> \
  --change-set-name <CHANGESET_NAME> \
  --profile <YOUR_PROFILE>
```

Once satisfied, execute it:

```bash
aws cloudformation execute-change-set \
  --stack-name <YOUR_STACK_NAME> \
  --change-set-name <CHANGESET_NAME> \
  --profile <YOUR_PROFILE>
```

---

## 9. Monitoring and Troubleshooting

### Check Stack Status

```bash
aws cloudformation describe-stacks \
  --stack-name <YOUR_STACK_NAME> \
  --query "Stacks[0].{Status:StackStatus,Reason:StackStatusReason}" \
  --output table \
  --profile <YOUR_PROFILE>
```

### View Stack Events

Useful for pinpointing which resource failed and why:

```bash
aws cloudformation describe-stack-events \
  --stack-name <YOUR_STACK_NAME> \
  --query "StackEvents[?ResourceStatus=='CREATE_FAILED' || ResourceStatus=='UPDATE_FAILED'].{Resource:LogicalResourceId,Status:ResourceStatus,Reason:ResourceStatusReason}" \
  --output table \
  --profile <YOUR_PROFILE>
```

For the full event log:

```bash
aws cloudformation describe-stack-events \
  --stack-name <YOUR_STACK_NAME> \
  --profile <YOUR_PROFILE>
```

### View Stack Outputs

After a successful deployment, inspect the outputs to get resource identifiers (collection endpoints, bucket names, table names, etc.):

```bash
aws cloudformation describe-stacks \
  --stack-name <YOUR_STACK_NAME> \
  --query "Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}" \
  --output table \
  --profile <YOUR_PROFILE>
```

### Common Failure Causes

| Symptom | Likely Cause | Fix |
|---|---|---|
| `S3 bucket already exists` | Another stack or account owns a bucket with the same name | Change `ProjectPrefix` to something unique |
| `Resource limit exceeded` for OpenSearch | Account-level collection limit reached | Request a service quota increase or delete unused collections |
| `CREATE_FAILED` on VPC endpoint | Security group or subnet doesn't belong to the specified VPC | Double-check that `InternalSGId`, `PrivateSubnetAId`, and `PrivateSubnetBId` all belong to the VPC specified in `VpcId` |
| `Parameter validation failed` on `ProjectPrefix` | Prefix doesn't match the allowed pattern | Use only lowercase letters, numbers, and hyphens. Must start and end with alphanumeric. Max 30 chars. |

---

## 10. Teardown

### Delete the RAG Pipeline Stack

```bash
aws cloudformation delete-stack \
  --stack-name <YOUR_STACK_NAME> \
  --profile <YOUR_PROFILE>
```

**Retained resources:** S3 buckets and DynamoDB tables with `DeletionPolicy: RetainExceptOnCreate` will survive stack deletion if they were successfully created. Delete them manually if desired:

```bash
# List retained buckets (they'll have your ProjectPrefix)
aws s3 ls | grep <YOUR_PROJECT_PREFIX>

# Empty and delete a retained bucket
aws s3 rb s3://<BUCKET_NAME> --force --profile <YOUR_PROFILE>
```

### Delete the VPC Stack (if deployed)

```bash
aws cloudformation delete-stack \
  --stack-name <YOUR_VPC_STACK_NAME> \
  --profile <YOUR_PROFILE>
```

The VPC stack has no retention policies, so all networking resources will be cleaned up automatically.

### Verify Deletion

```bash
aws cloudformation describe-stacks \
  --stack-name <YOUR_STACK_NAME> \
  --profile <YOUR_PROFILE>
```

A `DELETE_COMPLETE` status (or a "does not exist" error) confirms the stack is gone.
