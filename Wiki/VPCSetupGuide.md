# VPC Setup Guide for RAG Pipeline Development

## Why Build a VPC?

The production target is GovCloud, where the RAG pipeline lives entirely inside a VPC with no public internet exposure. This guide sets up a VPC in a standard commercial AWS account that mirrors that constraint, giving you a 1:1 rehearsal environment for stack deployment and networking behavior.

Nothing in this VPC will have a public IP, a public subnet, or an internet gateway. If a resource needs to talk to an AWS service, it does so through a VPC endpoint.

## Architecture

```
VPC (10.0.0.0/16)
├── Private Subnet A (10.0.1.0/24) — AZ 1
├── Private Subnet B (10.0.2.0/24) — AZ 2
├── Route Table (local traffic only, no internet route)
├── VPC Endpoints (gateway + interface, as needed)
└── Security Group (internal-only traffic)
```

Two subnets across two Availability Zones gives you the multi-AZ redundancy that most AWS services require (OpenSearch Serverless, Lambda in VPC, etc.) while keeping everything private.

## CloudFormation Template

Create a file called `vpc-stack.json` in the project root alongside the other stacks.

```json
{
  "AWSTemplateFormatVersion": "2010-09-09",
  "Description": "Private VPC with two isolated subnets for RAG pipeline development. No public access.",

  "Parameters": {
    "EnvironmentName": {
      "Type": "String",
      "Default": "rag-dev",
      "Description": "Prefix for resource names"
    },
    "VpcCidr": {
      "Type": "String",
      "Default": "10.0.0.0/16",
      "Description": "CIDR block for the VPC"
    },
    "SubnetACidr": {
      "Type": "String",
      "Default": "10.0.1.0/24",
      "Description": "CIDR block for private subnet A"
    },
    "SubnetBCidr": {
      "Type": "String",
      "Default": "10.0.2.0/24",
      "Description": "CIDR block for private subnet B"
    }
  },

  "Resources": {
    "VPC": {
      "Type": "AWS::EC2::VPC",
      "Properties": {
        "CidrBlock": { "Ref": "VpcCidr" },
        "EnableDnsSupport": true,
        "EnableDnsHostnames": true,
        "Tags": [
          {
            "Key": "Name",
            "Value": { "Fn::Sub": "${EnvironmentName}-vpc" }
          },
          {
            "Key": "Environment",
            "Value": { "Ref": "EnvironmentName" }
          },
          {
            "Key": "Project",
            "Value": "rag-pipeline"
          }
        ]
      }
    },

    "PrivateSubnetA": {
      "Type": "AWS::EC2::Subnet",
      "Properties": {
        "VpcId": { "Ref": "VPC" },
        "CidrBlock": { "Ref": "SubnetACidr" },
        "AvailabilityZone": { "Fn::Select": [ "0", { "Fn::GetAZs": "" } ] },
        "MapPublicIpOnLaunch": false,
        "Tags": [
          {
            "Key": "Name",
            "Value": { "Fn::Sub": "${EnvironmentName}-private-a" }
          },
          {
            "Key": "Environment",
            "Value": { "Ref": "EnvironmentName" }
          },
          {
            "Key": "Project",
            "Value": "rag-pipeline"
          }
        ]
      }
    },

    "PrivateSubnetB": {
      "Type": "AWS::EC2::Subnet",
      "Properties": {
        "VpcId": { "Ref": "VPC" },
        "CidrBlock": { "Ref": "SubnetBCidr" },
        "AvailabilityZone": { "Fn::Select": [ "1", { "Fn::GetAZs": "" } ] },
        "MapPublicIpOnLaunch": false,
        "Tags": [
          {
            "Key": "Name",
            "Value": { "Fn::Sub": "${EnvironmentName}-private-b" }
          },
          {
            "Key": "Environment",
            "Value": { "Ref": "EnvironmentName" }
          },
          {
            "Key": "Project",
            "Value": "rag-pipeline"
          }
        ]
      }
    },

    "PrivateRouteTable": {
      "Type": "AWS::EC2::RouteTable",
      "Properties": {
        "VpcId": { "Ref": "VPC" },
        "Tags": [
          {
            "Key": "Name",
            "Value": { "Fn::Sub": "${EnvironmentName}-private-rt" }
          },
          {
            "Key": "Environment",
            "Value": { "Ref": "EnvironmentName" }
          },
          {
            "Key": "Project",
            "Value": "rag-pipeline"
          }
        ]
      }
    },

    "SubnetARouteTableAssociation": {
      "Type": "AWS::EC2::SubnetRouteTableAssociation",
      "Properties": {
        "SubnetId": { "Ref": "PrivateSubnetA" },
        "RouteTableId": { "Ref": "PrivateRouteTable" }
      }
    },

    "SubnetBRouteTableAssociation": {
      "Type": "AWS::EC2::SubnetRouteTableAssociation",
      "Properties": {
        "SubnetId": { "Ref": "PrivateSubnetB" },
        "RouteTableId": { "Ref": "PrivateRouteTable" }
      }
    },

    "InternalSecurityGroup": {
      "Type": "AWS::EC2::SecurityGroup",
      "Properties": {
        "GroupDescription": "Allow TCP, UDP, and ICMP traffic only within the VPC CIDR. No external access.",
        "VpcId": { "Ref": "VPC" },
        "SecurityGroupIngress": [
          {
            "IpProtocol": "tcp",
            "FromPort": 0,
            "ToPort": 65535,
            "CidrIp": { "Ref": "VpcCidr" },
            "Description": "Allow all TCP from within VPC"
          },
          {
            "IpProtocol": "udp",
            "FromPort": 0,
            "ToPort": 65535,
            "CidrIp": { "Ref": "VpcCidr" },
            "Description": "Allow all UDP from within VPC"
          },
          {
            "IpProtocol": "icmp",
            "FromPort": -1,
            "ToPort": -1,
            "CidrIp": { "Ref": "VpcCidr" },
            "Description": "Allow ICMP from within VPC"
          }
        ],
        "SecurityGroupEgress": [
          {
            "IpProtocol": "tcp",
            "FromPort": 0,
            "ToPort": 65535,
            "CidrIp": { "Ref": "VpcCidr" },
            "Description": "Allow all TCP to within VPC"
          },
          {
            "IpProtocol": "udp",
            "FromPort": 0,
            "ToPort": 65535,
            "CidrIp": { "Ref": "VpcCidr" },
            "Description": "Allow all UDP to within VPC"
          },
          {
            "IpProtocol": "icmp",
            "FromPort": -1,
            "ToPort": -1,
            "CidrIp": { "Ref": "VpcCidr" },
            "Description": "Allow ICMP to within VPC"
          }
        ],
        "Tags": [
          {
            "Key": "Name",
            "Value": { "Fn::Sub": "${EnvironmentName}-internal-sg" }
          },
          {
            "Key": "Environment",
            "Value": { "Ref": "EnvironmentName" }
          },
          {
            "Key": "Project",
            "Value": "rag-pipeline"
          }
        ]
      }
    },

    "S3GatewayEndpoint": {
      "Type": "AWS::EC2::VPCEndpoint",
      "Properties": {
        "VpcId": { "Ref": "VPC" },
        "ServiceName": { "Fn::Sub": "com.amazonaws.${AWS::Region}.s3" },
        "VpcEndpointType": "Gateway",
        "RouteTableIds": [
          { "Ref": "PrivateRouteTable" }
        ]
      }
    },

    "DynamoDBGatewayEndpoint": {
      "Type": "AWS::EC2::VPCEndpoint",
      "Properties": {
        "VpcId": { "Ref": "VPC" },
        "ServiceName": { "Fn::Sub": "com.amazonaws.${AWS::Region}.dynamodb" },
        "VpcEndpointType": "Gateway",
        "RouteTableIds": [
          { "Ref": "PrivateRouteTable" }
        ]
      }
    }
  },

  "Outputs": {
    "VpcId": {
      "Description": "VPC ID",
      "Value": { "Ref": "VPC" },
      "Export": { "Name": { "Fn::Sub": "${EnvironmentName}-VpcId" } }
    },
    "PrivateSubnetAId": {
      "Description": "Private Subnet A ID",
      "Value": { "Ref": "PrivateSubnetA" },
      "Export": { "Name": { "Fn::Sub": "${EnvironmentName}-PrivateSubnetAId" } }
    },
    "PrivateSubnetBId": {
      "Description": "Private Subnet B ID",
      "Value": { "Ref": "PrivateSubnetB" },
      "Export": { "Name": { "Fn::Sub": "${EnvironmentName}-PrivateSubnetBId" } }
    },
    "InternalSecurityGroupId": {
      "Description": "Security group for internal VPC traffic",
      "Value": { "Ref": "InternalSecurityGroup" },
      "Export": { "Name": { "Fn::Sub": "${EnvironmentName}-InternalSGId" } }
    }
  }
}
```

## What's Intentionally Missing

- **Internet Gateway**: No IGW means nothing routes to the public internet. This is the point.
- **NAT Gateway**: NAT would allow outbound internet access from private subnets. We don't want that. AWS service access goes through VPC endpoints instead.
- **Public subnets**: Both subnets are private. `MapPublicIpOnLaunch` is `false` on both.

## What's Included and Why

| Resource | Purpose |
|---|---|
| VPC with DNS enabled | `EnableDnsSupport` and `EnableDnsHostnames` are required for VPC endpoints to resolve correctly |
| Two private subnets in separate AZs | Multi-AZ is required by Lambda VPC configurations and OpenSearch Serverless |
| Single route table | Only contains the local route (auto-created). No internet-bound routes exist |
| Internal security group | Allows TCP, UDP, and ICMP within the VPC CIDR with descriptions on each rule. Egress is also locked to VPC-only. Uses explicit protocols instead of `-1` (all) to pass cfn-guard compliance checks. Note: cfn-guard will still flag the 0-65535 port ranges (it prefers single-port rules), but narrowing to individual ports isn't practical for a general-purpose internal SG — scope it tighter per-service as you add resources |
| S3 Gateway Endpoint | Lets Lambda and other resources reach S3 without internet access. Gateway endpoints are free |
| DynamoDB Gateway Endpoint | Same rationale as S3. The pipeline uses DynamoDB for document/chunk metadata |

## VPC Endpoints You'll Likely Need Later

As you wire up more pipeline services inside this VPC, you'll need Interface VPC Endpoints for services that don't support gateway endpoints. Unlike gateway endpoints, interface endpoints cost ~$0.01/hr per AZ plus data processing fees, so add them as needed rather than all at once.

| Service | Endpoint Service Name | When You Need It |
|---|---|---|
| Bedrock Runtime | `com.amazonaws.{region}.bedrock-runtime` | When Lambda calls Bedrock for embeddings/generation |
| Bedrock Control Plane | `com.amazonaws.{region}.bedrock` | When Lambda needs to list/manage Bedrock models |
| SQS | `com.amazonaws.{region}.sqs` | When Lambda sends/receives SQS messages from inside the VPC |
| Step Functions | `com.amazonaws.{region}.states` | When resources inside the VPC interact with Step Functions (commercial regions only — see GovCloud note below) |
| CloudWatch Logs | `com.amazonaws.{region}.logs` | When Lambda in VPC needs to write logs |
| STS | `com.amazonaws.{region}.sts` | When Lambda assumes roles from inside the VPC |
| Secrets Manager | `com.amazonaws.{region}.secretsmanager` | If storing API keys or credentials |

Interface endpoints require the security group to allow HTTPS (port 443) inbound from the VPC CIDR. The `InternalSecurityGroup` in the template already covers this since it allows all TCP within the VPC.

## Deployment

This stack has no dependencies on the other pipeline stacks, so deploy it first:

```bash
aws cloudformation deploy \
  --template-file vpc-stack.json \
  --stack-name rag-dev-vpc \
  --profile data-scientist
```

Other stacks can then import the VPC outputs using cross-stack references:

```json
{ "Fn::ImportValue": "rag-dev-VpcId" }
{ "Fn::ImportValue": "rag-dev-PrivateSubnetAId" }
{ "Fn::ImportValue": "rag-dev-PrivateSubnetBId" }
{ "Fn::ImportValue": "rag-dev-InternalSGId" }
```

## GovCloud Considerations

The CloudFormation template works in GovCloud (`us-gov-west-1`, `us-gov-east-1`) — the `Fn::Sub` with `${AWS::Region}` resolves correctly for gateway endpoints (S3, DynamoDB) since they follow the standard `com.amazonaws.{region}` format in GovCloud.

However, there are important differences for interface endpoints:

| Service | Commercial Endpoint Name | GovCloud Endpoint Name | GovCloud Availability |
|---|---|---|---|
| S3 (Gateway) | `com.amazonaws.{region}.s3` | `com.amazonaws.us-gov-{x}-1.s3` | Both regions |
| DynamoDB (Gateway) | `com.amazonaws.{region}.dynamodb` | `com.amazonaws.us-gov-{x}-1.dynamodb` | Both regions |
| Bedrock | `com.amazonaws.{region}.bedrock` | `bedrock.gov-us-west-1.amazonaws.com` | us-gov-west-1 only |
| Bedrock Runtime | `com.amazonaws.{region}.bedrock-runtime` | `bedrock-runtime.gov-us-west-1.amazonaws.com` | us-gov-west-1 only |
| SQS | `com.amazonaws.{region}.sqs` | `com.amazonaws.us-gov-{x}-1.sqs` | Both regions |
| CloudWatch Logs | `com.amazonaws.{region}.logs` | `com.amazonaws.us-gov-{x}-1.logs` | Both regions |
| STS | `com.amazonaws.{region}.sts` | `com.amazonaws.us-gov-{x}-1.sts` | Both regions |
| Secrets Manager | `com.amazonaws.{region}.secretsmanager` | `com.amazonaws.us-gov-{x}-1.secretsmanager` | Both regions |
| Step Functions | `com.amazonaws.{region}.states` | Not listed | Not currently listed in GovCloud VPC endpoints |

Key takeaways:
- Bedrock VPC endpoints in GovCloud use a different naming convention (`bedrock.gov-us-west-1.amazonaws.com` instead of `com.amazonaws.{region}.bedrock`) and are only available in `us-gov-west-1`. You'll need to conditionally handle this in your templates if targeting GovCloud.
- Step Functions (`states`) does not appear in the GovCloud VPC endpoints list as of this writing. Verify with `aws ec2 describe-vpc-endpoint-services` in your GovCloud account before relying on it.
- The GovCloud VPC endpoints list is manually maintained by AWS and may lag behind actual availability. Always confirm with the CLI: `aws ec2 describe-vpc-endpoint-services --region us-gov-west-1 --query 'ServiceNames'`.
