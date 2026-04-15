# Implementation Plan: CloudFormation Stack for ImportDocuments Lambda

## Overview

Create the `import-documents-stack.json` CloudFormation template with 4 resources (IAM role, Lambda function, CloudWatch Logs VPC endpoint, Secrets Manager VPC endpoint), update the orchestrator stack to include it as a nested stack, update `sharepoint_auth.py` to retrieve the client secret from Secrets Manager, and write structural validation tests.

## Tasks

- [x] 1. Create the CloudFormation template file with parameters and metadata
  - Create `import-documents-stack.json` with `AWSTemplateFormatVersion`, `Description` (mentioning S3 Gateway Endpoint dependency per Req 8.3), and all 16 parameters
  - Parameters: `ProjectPrefix` (max 30, pattern `^[a-z0-9][a-z0-9\-]*[a-z0-9]$`), `EnvironmentTag`, `VpcId` (AWS::EC2::VPC::Id), `PrivateSubnetAId` (AWS::EC2::Subnet::Id), `PrivateSubnetBId` (AWS::EC2::Subnet::Id), `InternalSGId` (AWS::EC2::SecurityGroup::Id), `PrivateRouteTableId` (String), `StorageStackName` (String), `LambdaS3Key` (String), `TenantId`, `ClientId`, `ClientSecretArn` (String), `SharepointUrl`, `DriveName`, `CsvCategories` (default `""`), `SharePointFolderPath` (default `""`)
  - No parameter shall accept the client secret as plain text
  - _Requirements: 2.1–2.13, 3.1, 3.3, 3.4, 8.3, 13.1–13.3, 14.3_

- [x] 2. Add the IAM Execution Role resource
  - Define `ImportDocumentsRole` (`AWS::IAM::Role`) named `${ProjectPrefix}-import-documents-role`
  - Trust policy: `lambda.amazonaws.com` only
  - S3 policy: `s3:PutObject`, `s3:PutObjectTagging` scoped to Raw_Documents_Bucket ARN via `Fn::ImportValue` from Storage_Stack
  - CloudWatch Logs policy: `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` scoped to the Lambda's log group ARN
  - VPC policy: `ec2:CreateNetworkInterface`, `ec2:DescribeNetworkInterfaces`, `ec2:DeleteNetworkInterface` with `Resource: "*"`
  - Secrets Manager policy: `secretsmanager:GetSecretValue` scoped to `ClientSecretArn` parameter
  - All ARNs use `${AWS::Partition}`, `${AWS::Region}`, `${AWS::AccountId}`
  - Tags: `Environment` from `EnvironmentTag`, `Project: RAGPipeline`
  - _Requirements: 5.1–5.7, 9.3, 11.3, 11.4, 13.1–13.3_

- [x] 3. Add the Lambda Function resource
  - Define `ImportDocumentsFunction` (`AWS::Lambda::Function`) named `${ProjectPrefix}-import-documents`
  - Runtime `python3.12`, Handler `import_documents.handler`, Timeout `120`, MemorySize `512`, Architectures `["x86_64"]`
  - Code: S3Bucket from `Fn::ImportValue: ${StorageStackName}-PipelineArtifactsBucketName`, S3Key from `LambdaS3Key` parameter
  - Role: `Fn::GetAtt: [ImportDocumentsRole, Arn]`
  - VpcConfig: SubnetIds `[PrivateSubnetAId, PrivateSubnetBId]`, SecurityGroupIds `[InternalSGId]`
  - DependsOn: `[CloudWatchLogsVpcEndpoint, SecretsManagerVpcEndpoint]`
  - Environment variables: `clientId`, `clientSecretArn`, `tenantId`, `sharepointUrl`, `driveName`, `outputBucket` (from `Fn::ImportValue: ${StorageStackName}-RawDocumentsBucketName`), `csvCategories`, `sharePointFolderPath`
  - Tags: `Environment` from `EnvironmentTag`, `Project: RAGPipeline`
  - _Requirements: 1.1–1.7, 3.2, 4.1–4.8, 6.1–6.3, 8.2, 9.1, 9.2, 11.1, 11.2, 13.1–13.3_

- [x] 4. Add VPC Interface Endpoints (CloudWatch Logs and Secrets Manager)
  - Define `CloudWatchLogsVpcEndpoint` (`AWS::EC2::VPCEndpoint`, type `Interface`) for `com.amazonaws.${AWS::Region}.logs`
  - Define `SecretsManagerVpcEndpoint` (`AWS::EC2::VPCEndpoint`, type `Interface`) for `com.amazonaws.${AWS::Region}.secretsmanager`
  - Both: VpcId from parameter, SubnetIds `[PrivateSubnetAId, PrivateSubnetBId]`, SecurityGroupIds `[InternalSGId]`, PrivateDnsEnabled `true`
  - Both: Tags `Environment` from `EnvironmentTag`, `Project: RAGPipeline`
  - Do NOT create an S3 VPC endpoint (Storage_Stack handles that)
  - _Requirements: 7.1–7.10, 8.1, 11.5–11.8_

- [x] 5. Add Stack Outputs
  - `ImportDocumentsFunctionArn` — Lambda ARN, export `${AWS::StackName}-ImportDocumentsFunctionArn`
  - `ImportDocumentsFunctionName` — Lambda name, export `${AWS::StackName}-ImportDocumentsFunctionName`
  - `ImportDocumentsRoleArn` — Role ARN, export `${AWS::StackName}-ImportDocumentsRoleArn`
  - `CloudWatchLogsVpcEndpointId` — Endpoint ID, export `${AWS::StackName}-CloudWatchLogsVpcEndpointId`
  - `SecretsManagerVpcEndpointId` — Endpoint ID, export `${AWS::StackName}-SecretsManagerVpcEndpointId`
  - _Requirements: 12.1–12.5_

- [x] 6. Checkpoint — Validate template structure
  - Ensure the template is valid JSON, all 16 parameters are defined, all 4 resources exist, all 5 outputs exist
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Update the orchestrator stack to include ImportDocumentsStack
  - Add `ImportDocumentsStack` resource (`AWS::CloudFormation::Stack`) to `rag-pipeline-orchestrator-stack.json`
  - Set `DependsOn: StorageStack` and `TemplateURL: import-documents-stack.json`
  - Pass all parameters: `ProjectPrefix`, `EnvironmentTag`, `VpcId`, `PrivateSubnetAId`, `PrivateSubnetBId`, `InternalSGId`, `PrivateRouteTableId`, `StorageStackName` (extracted from `StorageStack` ref), `LambdaS3Key`, `TenantId`, `ClientId`, `ClientSecretArn`, `SharepointUrl`, `DriveName`, `CsvCategories`, `SharePointFolderPath`
  - Add new orchestrator-level parameters for ImportDocuments-specific values: `TenantId`, `ClientId`, `ClientSecretArn`, `SharepointUrl`, `DriveName`, `ImportDocumentsLambdaS3Key`, `CsvCategories`, `SharePointFolderPath`
  - Add orchestrator outputs for the new nested stack (function ARN, function name, role ARN, endpoint IDs)
  - _Requirements: 10.1–10.4_

- [x] 8. Update `sharepoint_auth.py` to retrieve client secret from Secrets Manager
  - Modify `get_access_token()` to read `clientSecretArn` from environment instead of `clientSecret`
  - Add a `boto3` call to `secretsmanager:GetSecretValue` using the ARN to retrieve the actual secret value at runtime
  - Keep backward compatibility: if `clientSecret` env var is set, use it directly (for local testing); otherwise use `clientSecretArn` + Secrets Manager
  - Update the `_client` initialization logic to use the retrieved secret
  - _Requirements: 3.2, 4.2, 5.5_

- [x] 9. Update `sharepoint_auth.py` tests for Secrets Manager integration
  - [x] 9.1 Update existing tests in `tests/test_sharepoint_auth.py` to account for the new `clientSecretArn` code path
    - Add tests for the Secrets Manager retrieval path: mock `boto3.client('secretsmanager')` and verify `GetSecretValue` is called with the correct ARN
    - Add test for fallback to `clientSecret` env var when `clientSecretArn` is not set
    - Add test for error handling when Secrets Manager call fails
    - _Requirements: 3.2, 4.2, 5.5_

- [x] 10. Write structural validation tests for the CloudFormation template
  - [x] 10.1 Create `tests/test_import_documents_stack.py` with template structural tests
    - Load and parse `import-documents-stack.json` as JSON
    - Verify all 16 parameters exist with correct types, constraints, and defaults
    - Verify all 4 resources exist with correct types (`AWS::IAM::Role`, `AWS::Lambda::Function`, 2x `AWS::EC2::VPCEndpoint`)
    - Verify Lambda configuration: Runtime, Handler, Timeout, MemorySize, Architectures, VpcConfig, Environment variables, DependsOn
    - Verify IAM role: trust policy, 4 inline policies with correct actions and resource scoping
    - Verify VPC endpoints: ServiceName, SubnetIds, SecurityGroupIds, PrivateDnsEnabled
    - Verify all taggable resources have `Environment` and `Project` tags
    - Verify all 5 outputs exist with correct export name patterns
    - Verify 3 `Fn::ImportValue` references use correct export names
    - Verify GovCloud compatibility: all ARN `Fn::Sub` strings use `${AWS::Partition}`, no hardcoded regions or account IDs
    - Verify security: no parameter named `clientSecret`/`ClientSecret`, no `{{resolve:secretsmanager` dynamic references, no S3 VPC endpoint resource
    - Verify Description mentions S3 Gateway Endpoint dependency
    - _Requirements: 1.1–1.7, 2.1–2.13, 3.1–3.4, 4.1–4.8, 5.1–5.7, 6.1–6.3, 7.1–7.10, 8.1–8.3, 9.1–9.3, 11.1–11.8, 12.1–12.5, 13.1–13.3, 14.3_

  - [x] 10.2 Add orchestrator consistency tests
    - Parse both `import-documents-stack.json` and `rag-pipeline-orchestrator-stack.json`
    - Verify every parameter the orchestrator passes to `ImportDocumentsStack` exists in the template
    - _Requirements: 10.1–10.4_

  - [x] 10.3 Add cross-stack export verification tests
    - Parse both `import-documents-stack.json` and `storage-stack.json`
    - Extract all `Fn::ImportValue` export names from the import-documents template
    - Verify each referenced export exists in storage-stack's Outputs
    - _Requirements: 9.1–9.3_

- [x] 10.4 Add cfn-lint validation test
    - Run `cfn-lint import-documents-stack.json` programmatically or as a subprocess
    - Assert zero errors
    - _Requirements: 14.1_

- [x] 10.5 Add cfn-guard compliance test
    - Run `cfn-guard` with default security rules
    - Assert zero critical violations
    - _Requirements: 14.2_

- [x] 11. Final checkpoint — Ensure all tests pass
  - Run `python3 -m pytest tests/test_import_documents_stack.py tests/test_sharepoint_auth.py -v`
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- This machine uses `python3`, not `python`. Always use `python3` and `python3 -m pytest` for running tests.
- Tasks marked with `*` are optional and can be skipped (cfn-lint and cfn-guard require CLI tools installed)
- The template is a static JSON file — no property-based testing applies; all tests are structural assertions
- The `sharepoint_auth.py` update (task 8) is a code change required by the design's note that the Lambda reads `clientSecretArn` instead of `clientSecret`
- Checkpoints ensure incremental validation before moving to the next phase
