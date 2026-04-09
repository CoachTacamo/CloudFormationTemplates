---
inclusion: manual
description: Maps all RAG pipeline AWS services to their VPC endpoint types and subnet requirements for both Commercial and GovCloud regions.
---

# VPC Endpoint Reference — RAG Pipeline Services

Quick reference for which VPC endpoint type each pipeline service needs and how subnet placement affects the requirement.

## Endpoint Types Explained

- **Gateway Endpoint**: Free. Injects a route into your route table pointing to the service. Only available for S3 and DynamoDB. Requires the `PrivateRouteTableId` parameter.
- **Interface Endpoint**: Uses AWS PrivateLink. Creates an ENI with a private IP in your subnet. Costs per-hour + per-GB. Requires a security group. Available for most AWS services.
- **No Endpoint Needed**: Service is invoked via IAM/SDK over the public internet, or the resource itself runs inside the VPC (e.g., Lambda in a VPC subnet).

## When Do You Need VPC Endpoints?

| Subnet Type | Internet Access | VPC Endpoints Required? |
|---|---|---|
| Public subnet (IGW route) | Yes | No — traffic routes to public service endpoints via IGW |
| Private subnet with NAT | Yes (outbound only) | Optional — but recommended to avoid NAT data processing costs and keep traffic on AWS backbone |
| Private subnet, no NAT | No | Yes — without endpoints, services are unreachable |

This pipeline uses private subnets with no NAT gateway, so all endpoints below are required.

---

## Core Pipeline Services

| AWS Service | Endpoint Type | Service Name Format | GovCloud Available | Notes |
|---|---|---|---|---|
| Amazon S3 | **Gateway** | `com.amazonaws.${Region}.s3` | us-gov-west-1, us-gov-east-1 | Free. Attaches to route table. Required for all bucket operations (raw docs, processed docs, embeddings, artifacts, logs, metadata). |
| Amazon DynamoDB | **Gateway** | `com.amazonaws.${Region}.dynamodb` | us-gov-west-1, us-gov-east-1 | Free. Attaches to route table. Required for Documents and Chunks table access. |
| OpenSearch Serverless | **Interface** | `com.amazonaws.${Region}.aoss` | us-gov-west-1, us-gov-east-1 | Uses PrivateLink. Requires security group allowing HTTPS (443). Created in the opensearch-stack. |
| Amazon Bedrock | **Interface** | `com.amazonaws.${Region}.bedrock-runtime` | us-gov-west-1, us-gov-east-1 | Required for embedding and generation calls from Lambda. Use `bedrock-runtime` for inference, `bedrock` for management API. |
| AWS Step Functions | **Interface** | `com.amazonaws.${Region}.states` | us-gov-west-1, us-gov-east-1 | Needed if Lambda functions call back to Step Functions (e.g., SendTaskSuccess). Not needed if Step Functions only invokes Lambda. |
| Amazon SQS | **Interface** | `com.amazonaws.${Region}.sqs` | us-gov-west-1, us-gov-east-1 | Required if Lambda in VPC sends/receives SQS messages for chunk buffering or DLQ. |
| Amazon EventBridge | **Interface** | `com.amazonaws.${Region}.events` | us-gov-west-1, us-gov-east-1 | Only needed if Lambda in VPC calls PutEvents. Not needed for S3→EventBridge→StepFunctions (that path is outside the VPC). |
| Amazon CloudWatch Logs | **Interface** | `com.amazonaws.${Region}.logs` | us-gov-west-1, us-gov-east-1 | Required for Lambda in VPC to ship logs. Without this, logs silently fail. |
| Amazon CloudWatch Monitoring | **Interface** | `com.amazonaws.${Region}.monitoring` | us-gov-west-1, us-gov-east-1 | Required for custom metrics from Lambda Powertools. |
| AWS X-Ray | **Interface** | `com.amazonaws.${Region}.xray` | us-gov-west-1, us-gov-east-1 | Required if active tracing is enabled on Lambda functions in VPC. |

## Optional / Situational Services

| AWS Service | Endpoint Type | Service Name Format | GovCloud Available | Notes |
|---|---|---|---|---|
| Amazon Textract | **Interface** | `com.amazonaws.${Region}.textract` | us-gov-west-1, us-gov-east-1 | Only needed if using OCR for scanned PDFs. |
| AWS KMS | **Interface** | `com.amazonaws.${Region}.kms` | us-gov-west-1, us-gov-east-1 | Required if using CMK encryption on S3, DynamoDB, SQS, or OpenSearch. Not needed for AWS-managed keys. |
| AWS STS | **Interface** | `com.amazonaws.${Region}.sts` | us-gov-west-1, us-gov-east-1 | Required if Lambda assumes cross-account roles or uses session tokens explicitly. |

## API Gateway — Special Case

API Gateway does not need a VPC endpoint for inbound traffic (it's a public-facing service by design). However, if you use a private API Gateway that should only be accessible from within the VPC, you need:

| AWS Service | Endpoint Type | Service Name Format | Notes |
|---|---|---|---|
| API Gateway (private) | **Interface** | `com.amazonaws.${Region}.execute-api` | Only for private APIs. Public/regional HTTP APIs don't need this. |

## Lambda — Special Case

Lambda itself doesn't need a VPC endpoint to be invoked. When Lambda runs in a VPC, it gets an ENI in your subnet. The endpoints above are needed for the services that Lambda calls out to, not for Lambda itself. However, if one Lambda needs to invoke another Lambda in the same VPC:

| AWS Service | Endpoint Type | Service Name Format | Notes |
|---|---|---|---|
| AWS Lambda | **Interface** | `com.amazonaws.${Region}.lambda` | Only needed for Lambda-to-Lambda invocations from within VPC. |

---

## GovCloud Considerations

- All service name formats use `com.amazonaws.${AWS::Region}.<service>` — the `Fn::Sub` pattern works identically in both partitions.
- GovCloud regions (`us-gov-west-1`, `us-gov-east-1`) support all endpoint types listed above.
- GovCloud compliance posture typically mandates private subnets with no NAT, making gateway and interface endpoints a hard requirement rather than an optimization.
- Interface endpoint costs are the same in GovCloud as commercial regions.
- Gateway endpoints remain free in GovCloud.

## CloudFormation Pattern

Gateway endpoint (S3/DynamoDB):
```json
{
  "Type": "AWS::EC2::VPCEndpoint",
  "Properties": {
    "VpcId": { "Ref": "VpcId" },
    "ServiceName": { "Fn::Sub": "com.amazonaws.${AWS::Region}.s3" },
    "VpcEndpointType": "Gateway",
    "RouteTableIds": [{ "Ref": "PrivateRouteTableId" }]
  }
}
```

Interface endpoint (everything else):
```json
{
  "Type": "AWS::EC2::VPCEndpoint",
  "Properties": {
    "VpcId": { "Ref": "VpcId" },
    "ServiceName": { "Fn::Sub": "com.amazonaws.${AWS::Region}.logs" },
    "VpcEndpointType": "Interface",
    "PrivateDnsEnabled": true,
    "SubnetIds": [
      { "Ref": "PrivateSubnetAId" },
      { "Ref": "PrivateSubnetBId" }
    ],
    "SecurityGroupIds": [{ "Ref": "InternalSGId" }]
  }
}
```

Note the key difference: Gateway endpoints take `RouteTableIds`, interface endpoints take `SubnetIds` + `SecurityGroupIds`. This is why `PrivateRouteTableId` is a separate parameter in the orchestrator stack.
