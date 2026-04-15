# Requirements Document

## Introduction

This specification defines the requirements for a CloudFormation template that deploys the Python ImportDocuments Lambda function (converted from C# in Milestones 1–4) as a nested stack within the RAG pipeline orchestrator. The stack targets AWS GovCloud (`us-gov-west-1`) and follows the exact integration patterns established by existing nested stacks (`storage-stack.json`, `dynamodb-stack.json`, `opensearch-stack.json`, `rds-stack.json`) in the orchestrator (`rag-pipeline-orchestrator-stack.json`).

The Lambda function must be deployed into the VPC's private subnets — this is mandatory, not optional. The existing C# Lambda runs outside the VPC with default internet access, which is a security gap; this stack fixes that by deploying the Python replacement inside the IT-managed VPC. The IT-managed VPC uses a Transit Gateway to route `0.0.0.0/0` traffic from private subnets to a centralized egress point for internet access — there is no NAT Gateway and no Internet Gateway. The IT-managed security group (passed as `InternalSGId`) allows outbound `0.0.0.0/0` on all ports, which is sufficient for the Lambda to reach Azure AD GovCloud and Microsoft Graph GovCloud endpoints via the Transit Gateway.

For best practice, this stack creates VPC interface endpoints for CloudWatch Logs and Secrets Manager to keep logging and secret-retrieval traffic on the AWS backbone, reduce Transit Gateway costs, and improve reliability. S3 and DynamoDB access are handled by existing gateway endpoints created by the Storage_Stack and DynamoDB_Stack respectively. The template must parameterize all configurable values, protect secrets from plain-text exposure using AWS Secrets Manager (the secret ARN is passed as a parameter and the Lambda retrieves the secret value at runtime via the Secrets Manager SDK), reference Lambda code from the pipeline artifacts S3 bucket, and tag all resources consistently.

### Prerequisites

The following IT-managed infrastructure must exist before deploying this stack:

- **VPC with Transit Gateway**: IT provides a VPC with a Transit Gateway that routes `0.0.0.0/0` traffic to a centralized egress point. The Transit Gateway (or equivalent internet egress path) must be operational for the Lambda to reach Azure AD GovCloud (`login.microsoftonline.us`) and Microsoft Graph GovCloud (`graph.microsoft.us`).
- **Private Subnets**: Two private subnets in different availability zones, routed through the Transit Gateway.
- **Security Group**: The IT-managed security group (passed as `InternalSGId`) with outbound `0.0.0.0/0` on all ports, corporate domain inbound, GovCloud Supernet inbound, and a self-referencing rule.
- **Private Route Table**: A route table associated with the private subnets, with a default route to the Transit Gateway.
- **Storage_Stack deployed**: The Storage_Stack must be deployed first, providing S3 buckets and the S3 Gateway Endpoint.
- **DynamoDB_Stack deployed**: The DynamoDB_Stack must be deployed first, providing the DynamoDB Gateway Endpoint.

## Glossary

- **Template**: The CloudFormation JSON template file (`import-documents-stack.json`) that defines all resources for the ImportDocuments Lambda deployment.
- **Stack**: The CloudFormation stack created by deploying the Template.
- **Orchestrator_Stack**: The parent CloudFormation stack (`rag-pipeline-orchestrator-stack.json`) that deploys all RAG pipeline nested stacks and passes VPC, subnet, security group, and route table parameters to each. These VPC-related parameters are IT-managed prerequisites passed into the Orchestrator_Stack, which then forwards them to nested stacks.
- **Lambda_Function**: The `AWS::Lambda::Function` resource that runs the Python ImportDocuments handler.
- **Execution_Role**: The `AWS::IAM::Role` resource that the Lambda_Function assumes at runtime.
- **Storage_Stack**: The separately deployed nested CloudFormation stack (`storage-stack.json`) that exports S3 bucket names, ARNs, the S3 Gateway Endpoint, and the pipeline artifacts bucket.
- **DynamoDB_Stack**: The separately deployed nested CloudFormation stack (`dynamodb-stack.json`) that exports DynamoDB table names, ARNs, and the DynamoDB Gateway Endpoint.
- **Pipeline_Artifacts_Bucket**: The S3 bucket (exported by Storage_Stack) where Lambda deployment zip packages are uploaded.
- **Raw_Documents_Bucket**: The S3 bucket (exported by Storage_Stack as `RawDocumentsBucketName` and `RawDocumentsBucketArn`) where the Lambda_Function writes imported SharePoint documents.
- **S3_Gateway_Endpoint**: The VPC Gateway Endpoint for S3 (created by Storage_Stack) that routes S3 traffic from private subnets over the AWS backbone without traversing the Transit Gateway.
- **DynamoDB_Gateway_Endpoint**: The VPC Gateway Endpoint for DynamoDB (created by DynamoDB_Stack) that routes DynamoDB traffic from private subnets over the AWS backbone without traversing the Transit Gateway.
- **InternalSecurityGroup**: The IT-managed security group passed as the `InternalSGId` parameter. It allows outbound `0.0.0.0/0` on all ports (enabling traffic to the Transit Gateway and VPC endpoints), with inbound rules for the corporate domain, GovCloud Supernet, and a self-referencing rule. It is not created by any pipeline stack — it is an IT-managed prerequisite.
- **Transit_Gateway**: An IT-managed AWS Transit Gateway that routes `0.0.0.0/0` traffic from private subnets to a centralized egress point for internet access. There is no NAT Gateway or Internet Gateway in the VPC.
- **CloudWatch_Logs_Endpoint**: An `AWS::EC2::VPCEndpoint` of type Interface for the `com.amazonaws.${AWS::Region}.logs` service, created by this Stack as a best practice to keep CloudWatch logging traffic on the AWS backbone rather than routing it through the Transit Gateway.
- **Secrets_Manager_Secret**: An AWS Secrets Manager secret that stores the Azure AD client secret. The secret ARN is passed as a stack parameter, and the Lambda retrieves the secret value at runtime using the Secrets Manager SDK.
- **Secrets_Manager_Endpoint**: An `AWS::EC2::VPCEndpoint` of type Interface for the `com.amazonaws.${AWS::Region}.secretsmanager` service, created by this Stack as a best practice to keep secret-retrieval traffic on the AWS backbone rather than routing it through the Transit Gateway.
- **ProjectPrefix**: A short lowercase alphanumeric-and-hyphen string used as a naming prefix for all resources, consistent with other RAG pipeline stacks.
- **Cross_Stack_Import**: A CloudFormation `Fn::ImportValue` reference to an output exported by another stack.

## Requirements

### Requirement 1: Lambda Function Resource

**User Story:** As a DevOps engineer, I want the Template to define a Lambda function with the correct Python 3.12 runtime configuration, so that the ImportDocuments handler runs with the same settings as the original C# Lambda.

#### Acceptance Criteria

1. THE Template SHALL define an `AWS::Lambda::Function` resource with Runtime set to `python3.12`.
2. THE Template SHALL configure the Lambda_Function Handler property to `import_documents.handler`.
3. THE Template SHALL configure the Lambda_Function Timeout property to `120` seconds.
4. THE Template SHALL configure the Lambda_Function MemorySize property to `512` MB.
5. THE Template SHALL configure the Lambda_Function Architectures property to include `x86_64`.
6. THE Template SHALL reference the Lambda deployment package via an S3 bucket and S3 key, where the S3 bucket is the Pipeline_Artifacts_Bucket.
7. THE Template SHALL name the Lambda_Function using the pattern `${ProjectPrefix}-import-documents`.

### Requirement 2: Stack Parameters for Orchestrator Integration

**User Story:** As a DevOps engineer, I want all configurable values exposed as stack parameters matching the orchestrator's parameter-passing pattern, so that the stack integrates as a nested stack without modification.

#### Acceptance Criteria

1. THE Template SHALL define a `ProjectPrefix` parameter with a max length of 30 characters and an allowed pattern of lowercase alphanumeric characters and hyphens.
2. THE Template SHALL define an `EnvironmentTag` parameter for tagging resources with the deployment environment.
3. THE Template SHALL define a `VpcId` parameter of type `AWS::EC2::VPC::Id`.
4. THE Template SHALL define a `PrivateSubnetAId` parameter of type `AWS::EC2::Subnet::Id`.
5. THE Template SHALL define a `PrivateSubnetBId` parameter of type `AWS::EC2::Subnet::Id`.
6. THE Template SHALL define an `InternalSGId` parameter of type `AWS::EC2::SecurityGroup::Id`.
7. THE Template SHALL define a `PrivateRouteTableId` parameter of type `String`.
8. THE Template SHALL define a `StorageStackName` parameter that identifies the Storage_Stack for Cross_Stack_Imports.
9. THE Template SHALL define parameters for each Lambda environment variable: `TenantId`, `ClientId`, `SharepointUrl`, `DriveName`, `CsvCategories`, and `SharePointFolderPath`.
10. THE Template SHALL define a `LambdaS3Key` parameter specifying the S3 object key of the Lambda deployment zip in the Pipeline_Artifacts_Bucket.
11. WHEN the `CsvCategories` parameter is not provided, THE Template SHALL default it to an empty string.
12. WHEN the `SharePointFolderPath` parameter is not provided, THE Template SHALL default it to an empty string.
13. THE Template SHALL define a `ClientSecretArn` parameter of type `String` that accepts the ARN of the Secrets_Manager_Secret containing the Azure AD client secret.

### Requirement 3: Secret Management

**User Story:** As a security engineer, I want the Azure AD client secret stored in AWS Secrets Manager and retrieved by the Lambda at runtime, so that the secret value never appears in CloudFormation parameters, template outputs, or Lambda environment variables visible in the console.

#### Acceptance Criteria

1. THE Template SHALL accept a `ClientSecretArn` parameter of type `String` containing the ARN of the Secrets_Manager_Secret.
2. THE Template SHALL set a `clientSecretArn` Lambda environment variable containing the `ClientSecretArn` parameter value, so that the Lambda_Function can retrieve the secret at runtime using the Secrets Manager SDK (`secretsmanager:GetSecretValue`).
3. THE Template SHALL NOT define any parameter that accepts the client secret as a plain-text `String` type.
4. THE Template SHALL NOT use a CloudFormation dynamic reference (`{{resolve:secretsmanager:...}}`) to inject the secret value into Lambda environment variables, because this would expose the secret in the Lambda console.

### Requirement 4: Lambda Environment Variables

**User Story:** As a DevOps engineer, I want the Lambda function's environment variables to be populated from stack parameters, so that the function receives the correct configuration for each deployment.

#### Acceptance Criteria

1. THE Template SHALL set the Lambda_Function environment variable `clientId` from the `ClientId` stack parameter.
2. THE Template SHALL set the Lambda_Function environment variable `clientSecretArn` from the `ClientSecretArn` stack parameter, so that the Lambda_Function retrieves the actual secret value at runtime using the Secrets Manager SDK.
3. THE Template SHALL set the Lambda_Function environment variable `tenantId` from the `TenantId` stack parameter.
4. THE Template SHALL set the Lambda_Function environment variable `sharepointUrl` from the `SharepointUrl` stack parameter.
5. THE Template SHALL set the Lambda_Function environment variable `driveName` from the `DriveName` stack parameter.
6. THE Template SHALL set the Lambda_Function environment variable `outputBucket` from the Raw_Documents_Bucket name, resolved via Cross_Stack_Import from the Storage_Stack using the export `${StorageStackName}-RawDocumentsBucketName`.
7. THE Template SHALL set the Lambda_Function environment variable `csvCategories` from the `CsvCategories` stack parameter.
8. THE Template SHALL set the Lambda_Function environment variable `sharePointFolderPath` from the `SharePointFolderPath` stack parameter.

### Requirement 5: IAM Execution Role

**User Story:** As a security engineer, I want the Lambda execution role to follow least-privilege principles, so that the function has only the permissions it needs to write to S3, log to CloudWatch, and operate within the VPC.

#### Acceptance Criteria

1. THE Template SHALL define an `AWS::IAM::Role` resource with a trust policy that allows only the `lambda.amazonaws.com` service to assume the role.
2. THE Execution_Role SHALL grant `s3:PutObject` and `s3:PutObjectTagging` permissions scoped to the Raw_Documents_Bucket ARN and its objects (`arn:${AWS::Partition}:s3:::${bucket}/*`).
3. THE Execution_Role SHALL grant `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` permissions scoped to the Lambda_Function's CloudWatch log group ARN.
4. THE Execution_Role SHALL grant `ec2:CreateNetworkInterface`, `ec2:DescribeNetworkInterfaces`, and `ec2:DeleteNetworkInterface` permissions scoped to the deployment region and account, because VPC attachment is mandatory.
5. THE Execution_Role SHALL grant `secretsmanager:GetSecretValue` permission scoped to the specific Secrets_Manager_Secret ARN passed as the `ClientSecretArn` parameter.
6. THE Execution_Role SHALL use `${AWS::Partition}` in all ARN constructions to support GovCloud (`aws-us-gov`) partition.
7. THE Template SHALL name the Execution_Role using the pattern `${ProjectPrefix}-import-documents-role`.

### Requirement 6: Mandatory VPC Configuration

**User Story:** As a DevOps engineer, I want the Lambda function deployed into the VPC's private subnets with the IT-managed security group, so that the function follows the same network isolation pattern as all other nested stacks in the RAG pipeline and closes the security gap of the existing C# Lambda running outside the VPC.

#### Acceptance Criteria

1. THE Template SHALL configure the Lambda_Function VpcConfig property with SubnetIds set to `PrivateSubnetAId` and `PrivateSubnetBId`.
2. THE Template SHALL configure the Lambda_Function VpcConfig SecurityGroupIds to include only the InternalSGId parameter value.
3. THE Lambda_Function SHALL always be deployed into the VPC — VPC configuration is mandatory, not optional or conditional.

### Requirement 7: VPC Interface Endpoints (CloudWatch Logs and Secrets Manager)

**User Story:** As a DevOps engineer, I want the stack to create VPC interface endpoints for CloudWatch Logs and Secrets Manager as a best practice, so that logging and secret-retrieval traffic stays on the AWS backbone, reduces Transit Gateway costs, and improves reliability compared to routing through the Transit Gateway.

#### Acceptance Criteria

1. THE Template SHALL create an `AWS::EC2::VPCEndpoint` resource of type `Interface` for the service `com.amazonaws.${AWS::Region}.logs`.
2. THE CloudWatch_Logs_Endpoint SHALL be associated with the subnets identified by `PrivateSubnetAId` and `PrivateSubnetBId`.
3. THE CloudWatch_Logs_Endpoint SHALL be associated with the InternalSGId security group, which allows the necessary inbound and outbound traffic for VPC endpoint communication.
4. THE CloudWatch_Logs_Endpoint SHALL have `PrivateDnsEnabled` set to `true` so that the standard CloudWatch Logs API endpoint resolves to the VPC endpoint's private IP addresses.
5. THE CloudWatch_Logs_Endpoint SHALL be tagged with `Environment` and `Project` tags consistent with other resources in the Stack.
6. THE Template SHALL create an `AWS::EC2::VPCEndpoint` resource of type `Interface` for the service `com.amazonaws.${AWS::Region}.secretsmanager`.
7. THE Secrets_Manager_Endpoint SHALL be associated with the subnets identified by `PrivateSubnetAId` and `PrivateSubnetBId`.
8. THE Secrets_Manager_Endpoint SHALL be associated with the InternalSGId security group.
9. THE Secrets_Manager_Endpoint SHALL have `PrivateDnsEnabled` set to `true` so that the standard Secrets Manager API endpoint resolves to the VPC endpoint's private IP addresses.
10. THE Secrets_Manager_Endpoint SHALL be tagged with `Environment` and `Project` tags consistent with other resources in the Stack.

### Requirement 8: S3 Access via Existing Gateway Endpoint

**User Story:** As a DevOps engineer, I want the requirements to acknowledge that S3 access from the Lambda function routes through the existing S3 Gateway Endpoint created by the Storage_Stack, so that no additional networking resources are needed for S3 operations.

#### Acceptance Criteria

1. THE Template SHALL NOT create an S3 VPC endpoint, because the Storage_Stack already creates an S3_Gateway_Endpoint attached to the PrivateRouteTableId.
2. THE Lambda_Function S3 PutObject calls to the Raw_Documents_Bucket SHALL route through the existing S3_Gateway_Endpoint, keeping S3 traffic on the AWS backbone without traversing the Transit Gateway.
3. THE Template Description or Metadata SHALL document the dependency on the Storage_Stack's S3_Gateway_Endpoint for S3 connectivity.

### Requirement 9: Cross-Stack References

**User Story:** As a DevOps engineer, I want the template to import values from the Storage_Stack, so that bucket names and ARNs are resolved dynamically and specifically target the Raw_Documents_Bucket.

#### Acceptance Criteria

1. THE Template SHALL use `Fn::ImportValue` with the Storage_Stack name to resolve the Pipeline_Artifacts_Bucket name for the Lambda code S3 bucket reference.
2. THE Template SHALL use `Fn::ImportValue` with the Storage_Stack name to resolve the Raw_Documents_Bucket name (export: `${StorageStackName}-RawDocumentsBucketName`) for the Lambda `outputBucket` environment variable.
3. THE Template SHALL use `Fn::ImportValue` with the Storage_Stack name to resolve the Raw_Documents_Bucket ARN (export: `${StorageStackName}-RawDocumentsBucketArn`) for the Execution_Role S3 permissions.

### Requirement 10: Orchestrator Integration Pattern

**User Story:** As a DevOps engineer, I want the import-documents stack designed as a nested stack within the orchestrator, so that it follows the same deployment and parameter-passing pattern as StorageStack, DynamoDBStack, OpenSearchStack, and RDSStack.

#### Acceptance Criteria

1. THE Template SHALL accept the same VPC-related parameters that the Orchestrator_Stack passes to other nested stacks: `VpcId`, `PrivateSubnetAId`, `PrivateSubnetBId`, `InternalSGId` (or `InternalSecurityGroupId`), and `PrivateRouteTableId`. These parameters represent IT-managed prerequisites that the Orchestrator_Stack receives and forwards to nested stacks.
2. THE Template SHALL accept `ProjectPrefix` and `EnvironmentTag` parameters matching the Orchestrator_Stack's parameter definitions.
3. THE Stack outputs SHALL follow the export naming pattern `${AWS::StackName}-{OutputName}`, consistent with Storage_Stack, DynamoDB_Stack, and other nested stacks.
4. THE Template SHALL be deployable as an `AWS::CloudFormation::Stack` resource within the Orchestrator_Stack, with the Orchestrator_Stack passing its VPC, subnet, security group, route table, ProjectPrefix, and EnvironmentTag parameters to this Stack.

### Requirement 11: Resource Tagging

**User Story:** As a DevOps engineer, I want all resources tagged with `Environment` and `Project` tags, so that cost allocation and resource identification are consistent across the RAG pipeline.

#### Acceptance Criteria

1. THE Template SHALL apply an `Environment` tag with the value of the `EnvironmentTag` parameter to the Lambda_Function resource.
2. THE Template SHALL apply a `Project` tag with the value `RAGPipeline` to the Lambda_Function resource.
3. THE Template SHALL apply an `Environment` tag with the value of the `EnvironmentTag` parameter to the Execution_Role resource.
4. THE Template SHALL apply a `Project` tag with the value `RAGPipeline` to the Execution_Role resource.
5. THE Template SHALL apply an `Environment` tag with the value of the `EnvironmentTag` parameter to the CloudWatch_Logs_Endpoint resource.
6. THE Template SHALL apply a `Project` tag with the value `RAGPipeline` to the CloudWatch_Logs_Endpoint resource.
7. THE Template SHALL apply an `Environment` tag with the value of the `EnvironmentTag` parameter to the Secrets_Manager_Endpoint resource.
8. THE Template SHALL apply a `Project` tag with the value `RAGPipeline` to the Secrets_Manager_Endpoint resource.

### Requirement 12: Stack Outputs

**User Story:** As a DevOps engineer, I want the stack to export key resource identifiers, so that downstream stacks or operational tooling can reference the Lambda function and networking resources.

#### Acceptance Criteria

1. THE Template SHALL output the Lambda_Function ARN with an export name following the pattern `${AWS::StackName}-ImportDocumentsFunctionArn`.
2. THE Template SHALL output the Lambda_Function name with an export name following the pattern `${AWS::StackName}-ImportDocumentsFunctionName`.
3. THE Template SHALL output the Execution_Role ARN with an export name following the pattern `${AWS::StackName}-ImportDocumentsRoleArn`.
4. THE Template SHALL output the CloudWatch_Logs_Endpoint ID with an export name following the pattern `${AWS::StackName}-CloudWatchLogsVpcEndpointId`.
5. THE Template SHALL output the Secrets_Manager_Endpoint ID with an export name following the pattern `${AWS::StackName}-SecretsManagerVpcEndpointId`.

### Requirement 13: GovCloud Compatibility

**User Story:** As a DevOps engineer deploying to AWS GovCloud, I want the template to use partition-aware ARN construction, so that the stack deploys correctly in the `aws-us-gov` partition.

#### Acceptance Criteria

1. THE Template SHALL use `${AWS::Partition}` in all ARN references instead of hardcoding `aws` or `aws-us-gov`.
2. THE Template SHALL use `${AWS::Region}` and `${AWS::AccountId}` pseudo-parameters in all region-specific and account-specific ARN constructions.
3. THE Template SHALL NOT contain any hardcoded region values or account IDs.

### Requirement 14: Template Validation

**User Story:** As a DevOps engineer, I want the template to pass CloudFormation linting and security compliance checks, so that deployment failures and security violations are caught before deployment.

#### Acceptance Criteria

1. WHEN the Template is validated with `cfn-lint`, THE Template SHALL produce zero errors.
2. WHEN the Template is checked with `cfn-guard` default security rules, THE Template SHALL produce zero critical violations.
3. THE Template SHALL use `AWSTemplateFormatVersion: "2010-09-09"` and include a `Description` field.
