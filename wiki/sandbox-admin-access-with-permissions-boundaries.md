# Sandbox Admin Access with IAM Permissions Boundaries

This document proposes a pattern for granting near-administrator access within an AWS sandbox (or development) account while maintaining organizational security guardrails. It is intended for IT administrators who manage AWS accounts and for developers who need to understand what they can and cannot do under this model.

---

## The Problem

A common anti-pattern in organizations new to AWS is **incremental permission granting** — adding one IAM action at a time as developers request it. This creates several issues:

- Developers are blocked constantly, waiting on IT to add permissions
- IT spends disproportionate time fielding permission requests
- The resulting policies become bloated, unstructured, and hard to audit
- Nobody is happy

The root cause is usually a lack of awareness of the mechanisms AWS provides to safely delegate broad access within a scoped boundary.

---

## What Is a Permissions Boundary?

An IAM **permissions boundary** is a managed policy that you attach to an IAM user or role to set the **maximum permissions** that entity can have. It does not grant permissions on its own — it acts as a ceiling.

### How Permissions Are Evaluated

When an IAM principal makes a request, AWS evaluates the **intersection** of:

1. **Identity-based policies** — the policies attached to the user/role (what you *want* to allow)
2. **Permissions boundary** — the maximum allowed scope (what you *can* allow)
3. **Service Control Policies (SCPs)** — organization-level guardrails (what the *account* is allowed to do)

```
Effective Permissions = Identity Policy ∩ Permissions Boundary ∩ SCPs
```

A request is only allowed if **all three** say yes. This means:

- A developer can have `AdministratorAccess` as their identity policy
- The permissions boundary can restrict that to "everything except IAM escalation and guardrail tampering"
- SCPs can further restrict the account to approved regions and services

Even with `AdministratorAccess`, the developer cannot exceed the boundary.

### Visual Model

```
┌─────────────────────────────────────────────────────────┐
│                  Service Control Policy                  │
│              (Organization / Account level)              │
│                                                         │
│   ┌─────────────────────────────────────────────────┐   │
│   │            Permissions Boundary                  │   │
│   │          (Attached to User / Role)               │   │
│   │                                                  │   │
│   │   ┌──────────────────────────────────────────┐   │   │
│   │   │         Identity-Based Policy            │   │   │
│   │   │     (AdministratorAccess or custom)       │   │   │
│   │   │                                          │   │   │
│   │   │    ████████████████████████████████████   │   │   │
│   │   │    █  Effective Permissions (overlap)  █   │   │   │
│   │   │    ████████████████████████████████████   │   │   │
│   │   └──────────────────────────────────────────┘   │   │
│   └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## The Proposed Model

### Layer 1 — SCPs (Managed by IT / Cloud Team)

Service Control Policies are applied at the AWS Organizations level. They affect every principal in the account, including root. Developers cannot see, modify, or remove them. SCPs should deny actions like:

- Leaving the AWS Organization
- Disabling CloudTrail or GuardDuty
- Creating resources in unapproved regions
- Modifying the SCPs themselves

This layer is entirely outside the developer's control and provides the ultimate safety net.

### Layer 2 — Permissions Boundary (Managed by IT / Cloud Team)

The boundary policy is attached to every developer user and role in the sandbox account. It defines the ceiling. The policy below is designed to give developers broad operational freedom while preventing privilege escalation and guardrail tampering.

### Layer 3 — Identity Policy (Can be AdministratorAccess)

Because the boundary constrains effective permissions, IT can safely attach `AdministratorAccess` (or a similarly broad policy) as the identity policy. Developers get to work without constant permission requests. IT gets to sleep at night.

---

## Sandbox Permissions Boundary Policy

The following policy is designed for sandbox and development accounts. It grants near-full access while explicitly denying actions that could compromise account security or allow privilege escalation.

### What Is Allowed

Under this boundary (when paired with `AdministratorAccess` as the identity policy), developers **can**:

| Category | Examples |
|---|---|
| Compute | Create/manage Lambda functions, EC2 instances, ECS clusters, Step Functions |
| Storage | Create/manage S3 buckets, EBS volumes, EFS file systems |
| Databases | Create/manage RDS instances, DynamoDB tables, OpenSearch collections, ElastiCache |
| Networking (read-only + endpoints) | Describe/view all VPC resources; create, modify, and delete VPC Gateway and Interface endpoints; manage security groups and load balancers |
| AI/ML | Access Bedrock models, SageMaker, Comprehend, Rekognition |
| Messaging | Create/manage SQS queues, SNS topics, EventBridge rules |
| IAM (scoped) | Create roles and policies **only if** the same permissions boundary is attached |
| Monitoring | CloudWatch metrics, logs, alarms, dashboards, X-Ray |
| Secrets | Create and manage Secrets Manager secrets and SSM parameters |
| CloudFormation | Deploy and manage stacks (with `CAPABILITY_NAMED_IAM`) |
| All other services | Generally allowed unless explicitly denied below |

### What Is Denied

| Denial | Why |
|---|---|
| Creating IAM users/roles **without** the permissions boundary attached | Prevents creating unbounded principals that escape the boundary |
| Deleting or modifying the permissions boundary policy itself | Prevents removing the ceiling |
| Modifying the boundary attachment on any user or role | Prevents detaching the boundary to escalate privileges |
| CloudTrail — `DeleteTrail`, `StopLogging`, `UpdateTrail` | Preserves audit logging |
| GuardDuty — `DeleteDetector`, `DisableOrganizationAdminAccount` | Preserves threat detection |
| AWS Config — `DeleteConfigurationRecorder`, `StopConfigurationRecorder` | Preserves compliance monitoring |
| AWS Organizations — all actions | Prevents account-level changes |
| IAM — `CreateUser`, `CreateLoginProfile`, `CreateAccessKey` for human users | Sandbox roles should use federated/SSO access, not long-lived credentials |
| Account-level settings — `CreateAccountAlias`, `DeleteAccountAlias` | Prevents account identity changes |
| VPC infrastructure — create/delete/modify VPCs, subnets, route tables, NAT gateways, internet gateways, peering, transit gateways, NACLs, Elastic IPs | VPC topology is managed by IT/network team. Developers can only manage VPC endpoints and security groups. |

### The Policy Document

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowFullAccessWithinBoundary",
      "Effect": "Allow",
      "Action": "*",
      "Resource": "*"
    },
    {
      "Sid": "DenyBoundaryPolicyModification",
      "Effect": "Deny",
      "Action": [
        "iam:DeletePolicy",
        "iam:DeletePolicyVersion",
        "iam:CreatePolicyVersion",
        "iam:SetDefaultPolicyVersion"
      ],
      "Resource": "arn:aws:iam::*:policy/SandboxPermissionsBoundary"
    },
    {
      "Sid": "DenyBoundaryRemoval",
      "Effect": "Deny",
      "Action": [
        "iam:DeleteUserPermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:PutUserPermissionsBoundary",
        "iam:PutRolePermissionsBoundary"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyRoleCreationWithoutBoundary",
      "Effect": "Deny",
      "Action": "iam:CreateRole",
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "iam:PermissionsBoundary": "arn:aws:iam::*:policy/SandboxPermissionsBoundary"
        }
      }
    },
    {
      "Sid": "DenyUserCreation",
      "Effect": "Deny",
      "Action": [
        "iam:CreateUser",
        "iam:CreateLoginProfile",
        "iam:UpdateLoginProfile",
        "iam:CreateAccessKey"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyCloudTrailTampering",
      "Effect": "Deny",
      "Action": [
        "cloudtrail:DeleteTrail",
        "cloudtrail:StopLogging",
        "cloudtrail:UpdateTrail",
        "cloudtrail:PutEventSelectors"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyGuardDutyTampering",
      "Effect": "Deny",
      "Action": [
        "guardduty:DeleteDetector",
        "guardduty:DeleteMembers",
        "guardduty:DisassociateFromMasterAccount",
        "guardduty:DisassociateMembers",
        "guardduty:DisableOrganizationAdminAccount"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyConfigTampering",
      "Effect": "Deny",
      "Action": [
        "config:DeleteConfigurationRecorder",
        "config:StopConfigurationRecorder",
        "config:DeleteDeliveryChannel"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyOrganizationsAccess",
      "Effect": "Deny",
      "Action": "organizations:*",
      "Resource": "*"
    },
    {
      "Sid": "DenyAccountLevelChanges",
      "Effect": "Deny",
      "Action": [
        "account:*",
        "iam:CreateAccountAlias",
        "iam:DeleteAccountAlias"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyVpcMutationExceptEndpoints",
      "Effect": "Deny",
      "Action": [
        "ec2:CreateVpc",
        "ec2:DeleteVpc",
        "ec2:ModifyVpcAttribute",
        "ec2:AssociateVpcCidrBlock",
        "ec2:DisassociateVpcCidrBlock",
        "ec2:CreateSubnet",
        "ec2:DeleteSubnet",
        "ec2:ModifySubnetAttribute",
        "ec2:CreateRouteTable",
        "ec2:DeleteRouteTable",
        "ec2:CreateRoute",
        "ec2:DeleteRoute",
        "ec2:ReplaceRoute",
        "ec2:AssociateRouteTable",
        "ec2:DisassociateRouteTable",
        "ec2:ReplaceRouteTableAssociation",
        "ec2:CreateInternetGateway",
        "ec2:DeleteInternetGateway",
        "ec2:AttachInternetGateway",
        "ec2:DetachInternetGateway",
        "ec2:CreateNatGateway",
        "ec2:DeleteNatGateway",
        "ec2:CreateVpnGateway",
        "ec2:DeleteVpnGateway",
        "ec2:AttachVpnGateway",
        "ec2:DetachVpnGateway",
        "ec2:CreateVpnConnection",
        "ec2:DeleteVpnConnection",
        "ec2:CreateVpcPeeringConnection",
        "ec2:DeleteVpcPeeringConnection",
        "ec2:AcceptVpcPeeringConnection",
        "ec2:RejectVpcPeeringConnection",
        "ec2:CreateTransitGateway",
        "ec2:DeleteTransitGateway",
        "ec2:CreateTransitGatewayVpcAttachment",
        "ec2:DeleteTransitGatewayVpcAttachment",
        "ec2:CreateDhcpOptions",
        "ec2:DeleteDhcpOptions",
        "ec2:AssociateDhcpOptions",
        "ec2:CreateNetworkAcl",
        "ec2:DeleteNetworkAcl",
        "ec2:CreateNetworkAclEntry",
        "ec2:DeleteNetworkAclEntry",
        "ec2:ReplaceNetworkAclEntry",
        "ec2:ReplaceNetworkAclAssociation",
        "ec2:AllocateAddress",
        "ec2:ReleaseAddress",
        "ec2:AssociateAddress",
        "ec2:DisassociateAddress"
      ],
      "Resource": "*"
    }
  ]
}
```

> **Important:** Replace the placeholder `arn:aws:iam::*:policy/SandboxPermissionsBoundary` with your actual account-specific ARN after creating the policy (e.g., `arn:aws:iam::123456789012:policy/SandboxPermissionsBoundary`). The wildcard account ID is used here for portability across accounts.

> **Note on VPC Endpoints:** The `DenyVpcMutationExceptEndpoints` statement blocks VPC infrastructure changes (VPCs, subnets, route tables, gateways, peering, NACLs, Elastic IPs) but does **not** block `ec2:CreateVpcEndpoint`, `ec2:DeleteVpcEndpoints`, or `ec2:ModifyVpcEndpoint`. Developers can freely manage Gateway and Interface endpoints for services like S3, DynamoDB, Secrets Manager, CloudWatch Logs, and others. All `ec2:Describe*` actions also remain available for read-only visibility into the VPC topology.

---

## Implementation Guide

### Step 1 — Create the Permissions Boundary Policy

This step is performed by the IT/Cloud team in each sandbox account (or via CloudFormation StackSets across all sandbox accounts).

```bash
# Create the permissions boundary policy
aws iam create-policy \
  --policy-name SandboxPermissionsBoundary \
  --policy-document file://Policies/sandbox-permissions-boundary.json \
  --description "Permissions boundary for sandbox account developers. Allows broad access while preventing privilege escalation and guardrail tampering."

# Note the ARN from the output — you will need it
# arn:aws:iam::123456789012:policy/SandboxPermissionsBoundary
```

### Step 2 — Update the Policy ARNs

After creating the policy, update the ARN references in the policy document itself. The `DenyBoundaryPolicyModification` and `DenyRoleCreationWithoutBoundary` statements reference the boundary by ARN. Replace the wildcard account ID with your actual account ID.

### Step 3 — Create a Developer Role with the Boundary

```bash
# Create the developer role (for SSO/federated access)
aws iam create-role \
  --role-name SandboxDeveloper \
  --assume-role-policy-document file://trust-policy.json \
  --permissions-boundary arn:aws:iam::123456789012:policy/SandboxPermissionsBoundary

# Attach AdministratorAccess as the identity policy
aws iam attach-role-policy \
  --role-name SandboxDeveloper \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
```

The trust policy depends on how your organization authenticates. For IAM Identity Center (SSO):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::MANAGEMENT_ACCOUNT_ID:root"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:PrincipalOrgID": "o-YOUR_ORG_ID"
        }
      }
    }
  ]
}
```

### Step 4 — Verify the Boundary Works

Test that the boundary prevents escalation:

```bash
# This should SUCCEED — creating a role WITH the boundary
aws iam create-role \
  --role-name TestLambdaRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  --permissions-boundary arn:aws:iam::123456789012:policy/SandboxPermissionsBoundary

# This should FAIL — creating a role WITHOUT the boundary
aws iam create-role \
  --role-name UnboundedRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
# Expected: AccessDenied

# This should FAIL — deleting the boundary policy
aws iam delete-policy \
  --policy-arn arn:aws:iam::123456789012:policy/SandboxPermissionsBoundary
# Expected: AccessDenied

# This should FAIL — removing the boundary from your own role
aws iam delete-role-permissions-boundary \
  --role-name SandboxDeveloper
# Expected: AccessDenied

# This should FAIL — creating a VPC
aws ec2 create-vpc --cidr-block 10.99.0.0/16
# Expected: AccessDenied (UnauthorizedOperation)

# This should FAIL — creating a subnet
aws ec2 create-subnet --vpc-id vpc-existing --cidr-block 10.0.99.0/24
# Expected: AccessDenied (UnauthorizedOperation)

# This should SUCCEED — describing VPC resources (read-only)
aws ec2 describe-vpcs
aws ec2 describe-subnets
aws ec2 describe-route-tables

# This should SUCCEED — creating a VPC endpoint
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-existing \
  --service-name com.amazonaws.us-east-1.s3 \
  --route-table-ids rtb-existing
```

### Step 5 — Layer SCPs on Top (Recommended)

For defense in depth, apply SCPs at the organizational unit (OU) level for all sandbox accounts. Example SCP:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyLeavingOrg",
      "Effect": "Deny",
      "Action": "organizations:LeaveOrganization",
      "Resource": "*"
    },
    {
      "Sid": "DenyDisablingCloudTrail",
      "Effect": "Deny",
      "Action": [
        "cloudtrail:DeleteTrail",
        "cloudtrail:StopLogging"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyUnapprovedRegions",
      "Effect": "Deny",
      "NotAction": [
        "iam:*",
        "sts:*",
        "support:*",
        "billing:*"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": [
            "us-east-1",
            "us-west-2",
            "us-gov-west-1"
          ]
        }
      }
    }
  ]
}
```

> **Note:** SCPs are managed at the AWS Organizations level by the management account. They cannot be modified from within the sandbox account.

---

## CloudFormation Considerations

When developers deploy CloudFormation stacks that create IAM roles (using `CAPABILITY_NAMED_IAM`), those roles must also have the permissions boundary attached. CloudFormation supports this natively:

```json
{
  "Type": "AWS::IAM::Role",
  "Properties": {
    "RoleName": "MyLambdaExecutionRole",
    "AssumeRolePolicyDocument": { "..." : "..." },
    "PermissionsBoundary": "arn:aws:iam::123456789012:policy/SandboxPermissionsBoundary",
    "Policies": [ "..." ]
  }
}
```

If a CloudFormation template tries to create a role without the boundary, the stack will fail with `AccessDenied` — which is the correct behavior.

---

## FAQ

**Q: Can a developer remove the boundary from their own role?**
No. The `DenyBoundaryRemoval` statement explicitly denies `iam:DeleteUserPermissionsBoundary` and `iam:DeleteRolePermissionsBoundary` on all resources.

**Q: Can a developer create a new role without the boundary and assume it?**
No. The `DenyRoleCreationWithoutBoundary` statement prevents creating any role that does not have the boundary attached.

**Q: Can a developer modify the boundary policy to make it more permissive?**
No. The `DenyBoundaryPolicyModification` statement prevents `CreatePolicyVersion`, `DeletePolicyVersion`, `SetDefaultPolicyVersion`, and `DeletePolicy` on the boundary policy itself.

**Q: What if a developer needs a permission that the boundary denies?**
They submit a request to IT. IT evaluates whether the boundary should be updated for all sandbox users, or whether the specific need should be handled through a separate, IT-managed role. This should be rare — the boundary only denies security-critical actions.

**Q: Does this work with IAM Identity Center (SSO)?**
Yes. Permission sets in IAM Identity Center support permissions boundaries. IT configures the permission set with `AdministratorAccess` as the inline policy and the boundary as the permissions boundary.

**Q: What about service-linked roles?**
Service-linked roles (created by AWS services like RDS, OpenSearch, etc.) are exempt from permissions boundaries. They are created with `iam:CreateServiceLinkedRole`, which is allowed by this policy. AWS manages their permissions directly.

**Q: Can this be applied across multiple accounts automatically?**
Yes. Use CloudFormation StackSets to deploy the boundary policy to all sandbox accounts in an OU. Pair with SCPs applied at the OU level for consistent guardrails.

**Q: Can a developer create or modify VPCs, subnets, or route tables?**
No. VPC infrastructure is managed by the IT/network team. The `DenyVpcMutationExceptEndpoints` statement blocks creation, deletion, and modification of VPCs, subnets, route tables, internet gateways, NAT gateways, VPN gateways, peering connections, transit gateways, NACLs, DHCP options, and Elastic IPs. Developers **can** create, modify, and delete VPC endpoints (both Gateway and Interface types), manage security groups, and use all `ec2:Describe*` actions for read-only visibility.

---

## Summary

| Layer | Who Manages It | What It Does | Can Developers Modify It? |
|---|---|---|---|
| SCP | IT / Cloud Team (Org level) | Account-wide guardrails | No — invisible to account users |
| Permissions Boundary | IT / Cloud Team (Account level) | Ceiling on developer permissions | No — self-modification is denied |
| Identity Policy | IT (initially), Developers (for service roles) | Grants actual permissions | Yes — but effective permissions cannot exceed the boundary |
| CloudTrail / GuardDuty / Config | IT / Cloud Team | Audit and threat detection | No — tampering is denied by boundary + SCP |

This model gives developers the freedom to build, experiment, and deploy in sandbox accounts without waiting on IT for every permission — while giving IT confidence that the account's security posture cannot be undermined from within.
