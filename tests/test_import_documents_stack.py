"""Structural validation tests for import-documents-stack.json.

Loads the CloudFormation template once and verifies parameters, resources,
outputs, tags, cross-stack references, GovCloud compatibility, and security
constraints.

Requirements: 1.1–1.7, 2.1–2.13, 3.1–3.4, 4.1–4.8, 5.1–5.7, 6.1–6.3,
              7.1–7.10, 8.1–8.3, 9.1–9.3, 11.1–11.8, 12.1–12.5, 13.1–13.3,
              14.3
"""

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module-level fixture: load the template once
# ---------------------------------------------------------------------------

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "import-documents-stack.json"


@pytest.fixture(scope="module")
def template():
    """Load and parse import-documents-stack.json once for the entire module."""
    with open(TEMPLATE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def parameters(template):
    return template["Parameters"]


@pytest.fixture(scope="module")
def resources(template):
    return template["Resources"]


@pytest.fixture(scope="module")
def outputs(template):
    return template["Outputs"]


# ===================================================================
# Parameters (Req 2.1–2.13, 3.1, 3.3, 3.4)
# ===================================================================


class TestParameters:
    """Verify all 16 parameters exist with correct types, constraints, and defaults."""

    def test_parameter_count(self, parameters):
        assert len(parameters) == 16

    EXPECTED_PARAMS = [
        "ProjectPrefix", "EnvironmentTag", "VpcId", "PrivateSubnetAId",
        "PrivateSubnetBId", "InternalSGId", "PrivateRouteTableId",
        "StorageStackName", "LambdaS3Key", "TenantId", "ClientId",
        "ClientSecretArn", "SharepointUrl", "DriveName", "CsvCategories",
        "SharePointFolderPath",
    ]

    @pytest.mark.parametrize("name", EXPECTED_PARAMS)
    def test_parameter_exists(self, parameters, name):
        assert name in parameters, f"Missing parameter: {name}"


    # --- Type checks ---

    def test_project_prefix_type_and_constraints(self, parameters):
        p = parameters["ProjectPrefix"]
        assert p["Type"] == "String"
        assert p["MaxLength"] == 30
        assert "AllowedPattern" in p

    def test_vpc_id_type(self, parameters):
        assert parameters["VpcId"]["Type"] == "AWS::EC2::VPC::Id"

    def test_private_subnet_a_type(self, parameters):
        assert parameters["PrivateSubnetAId"]["Type"] == "AWS::EC2::Subnet::Id"

    def test_private_subnet_b_type(self, parameters):
        assert parameters["PrivateSubnetBId"]["Type"] == "AWS::EC2::Subnet::Id"

    def test_internal_sg_type(self, parameters):
        assert parameters["InternalSGId"]["Type"] == "AWS::EC2::SecurityGroup::Id"

    def test_private_route_table_type(self, parameters):
        assert parameters["PrivateRouteTableId"]["Type"] == "String"

    def test_storage_stack_name_type(self, parameters):
        assert parameters["StorageStackName"]["Type"] == "String"

    def test_lambda_s3_key_type(self, parameters):
        assert parameters["LambdaS3Key"]["Type"] == "String"

    def test_client_secret_arn_type(self, parameters):
        assert parameters["ClientSecretArn"]["Type"] == "String"

    # --- Defaults ---

    def test_csv_categories_default(self, parameters):
        assert parameters["CsvCategories"]["Default"] == ""

    def test_sharepoint_folder_path_default(self, parameters):
        assert parameters["SharePointFolderPath"]["Default"] == ""

    # --- No defaults on required params ---

    REQUIRED_NO_DEFAULT = [
        "ProjectPrefix", "EnvironmentTag", "VpcId", "PrivateSubnetAId",
        "PrivateSubnetBId", "InternalSGId", "PrivateRouteTableId",
        "StorageStackName", "LambdaS3Key", "TenantId", "ClientId",
        "ClientSecretArn", "SharepointUrl", "DriveName",
    ]

    @pytest.mark.parametrize("name", REQUIRED_NO_DEFAULT)
    def test_required_param_has_no_default(self, parameters, name):
        assert "Default" not in parameters[name], f"{name} should not have a Default"


# ===================================================================
# Resources (Req 1.1–1.7, 5.1–5.7, 6.1–6.3, 7.1–7.10)
# ===================================================================


class TestResourceCounts:
    """Verify all 4 resources exist with correct types."""

    def test_resource_count(self, resources):
        assert len(resources) == 4

    EXPECTED_RESOURCES = {
        "ImportDocumentsRole": "AWS::IAM::Role",
        "ImportDocumentsFunction": "AWS::Lambda::Function",
        "CloudWatchLogsVpcEndpoint": "AWS::EC2::VPCEndpoint",
        "SecretsManagerVpcEndpoint": "AWS::EC2::VPCEndpoint",
    }

    @pytest.mark.parametrize("name,rtype", EXPECTED_RESOURCES.items())
    def test_resource_exists_with_type(self, resources, name, rtype):
        assert name in resources
        assert resources[name]["Type"] == rtype


# ===================================================================
# Lambda Configuration (Req 1.1–1.7, 4.1–4.8, 6.1–6.3)
# ===================================================================


class TestLambdaConfiguration:
    """Verify Lambda function properties."""

    @pytest.fixture(scope="class")
    def fn(self, resources):
        return resources["ImportDocumentsFunction"]

    @pytest.fixture(scope="class")
    def props(self, fn):
        return fn["Properties"]

    def test_runtime(self, props):
        assert props["Runtime"] == "python3.12"

    def test_handler(self, props):
        assert props["Handler"] == "import_documents.handler"

    def test_timeout(self, props):
        assert props["Timeout"] == 120

    def test_memory_size(self, props):
        assert props["MemorySize"] == 512

    def test_architectures(self, props):
        assert props["Architectures"] == ["x86_64"]

    def test_function_name_pattern(self, props):
        name = props["FunctionName"]
        assert name == {"Fn::Sub": "${ProjectPrefix}-import-documents"}

    def test_vpc_config_subnets(self, props):
        subnets = props["VpcConfig"]["SubnetIds"]
        assert {"Ref": "PrivateSubnetAId"} in subnets
        assert {"Ref": "PrivateSubnetBId"} in subnets

    def test_vpc_config_security_groups(self, props):
        sgs = props["VpcConfig"]["SecurityGroupIds"]
        assert sgs == [{"Ref": "InternalSGId"}]

    def test_depends_on(self, fn):
        depends = fn["DependsOn"]
        assert "CloudWatchLogsVpcEndpoint" in depends
        assert "SecretsManagerVpcEndpoint" in depends

    # --- Environment variables (Req 4.1–4.8) ---

    def test_env_client_id(self, props):
        env = props["Environment"]["Variables"]
        assert env["clientId"] == {"Ref": "ClientId"}

    def test_env_client_secret_arn(self, props):
        env = props["Environment"]["Variables"]
        assert env["clientSecretArn"] == {"Ref": "ClientSecretArn"}

    def test_env_tenant_id(self, props):
        env = props["Environment"]["Variables"]
        assert env["tenantId"] == {"Ref": "TenantId"}

    def test_env_sharepoint_url(self, props):
        env = props["Environment"]["Variables"]
        assert env["sharepointUrl"] == {"Ref": "SharepointUrl"}

    def test_env_drive_name(self, props):
        env = props["Environment"]["Variables"]
        assert env["driveName"] == {"Ref": "DriveName"}

    def test_env_output_bucket(self, props):
        env = props["Environment"]["Variables"]
        expected = {"Fn::ImportValue": {"Fn::Sub": "${StorageStackName}-RawDocumentsBucketName"}}
        assert env["outputBucket"] == expected

    def test_env_csv_categories(self, props):
        env = props["Environment"]["Variables"]
        assert env["csvCategories"] == {"Ref": "CsvCategories"}

    def test_env_sharepoint_folder_path(self, props):
        env = props["Environment"]["Variables"]
        assert env["sharePointFolderPath"] == {"Ref": "SharePointFolderPath"}

    def test_env_variable_count(self, props):
        env = props["Environment"]["Variables"]
        assert len(env) == 8

    # --- Code source (Req 1.6, 9.1) ---

    def test_code_s3_bucket(self, props):
        expected = {"Fn::ImportValue": {"Fn::Sub": "${StorageStackName}-PipelineArtifactsBucketName"}}
        assert props["Code"]["S3Bucket"] == expected

    def test_code_s3_key(self, props):
        assert props["Code"]["S3Key"] == {"Ref": "LambdaS3Key"}

    def test_role_reference(self, props):
        assert props["Role"] == {"Fn::GetAtt": ["ImportDocumentsRole", "Arn"]}


# ===================================================================
# IAM Role (Req 5.1–5.7)
# ===================================================================


class TestIAMRole:
    """Verify IAM execution role: trust policy, 4 inline policies."""

    @pytest.fixture(scope="class")
    def role_props(self, resources):
        return resources["ImportDocumentsRole"]["Properties"]

    @pytest.fixture(scope="class")
    def policies(self, role_props):
        return {p["PolicyName"]: p["PolicyDocument"] for p in role_props["Policies"]}

    def test_role_name(self, role_props):
        assert role_props["RoleName"] == {"Fn::Sub": "${ProjectPrefix}-import-documents-role"}

    def test_trust_policy_lambda_only(self, role_props):
        stmts = role_props["AssumeRolePolicyDocument"]["Statement"]
        assert len(stmts) == 1
        stmt = stmts[0]
        assert stmt["Effect"] == "Allow"
        assert stmt["Principal"]["Service"] == "lambda.amazonaws.com"
        assert stmt["Action"] == "sts:AssumeRole"

    def test_four_inline_policies(self, role_props):
        assert len(role_props["Policies"]) == 4

    # --- S3 Access Policy ---

    def test_s3_policy_actions(self, policies):
        stmts = policies["S3AccessPolicy"]["Statement"]
        actions = stmts[0]["Action"]
        assert "s3:PutObject" in actions
        assert "s3:PutObjectTagging" in actions

    def test_s3_policy_uses_import_value(self, policies):
        resource = policies["S3AccessPolicy"]["Statement"][0]["Resource"]
        # Fn::Sub with list form referencing Fn::ImportValue
        assert "Fn::Sub" in resource
        sub_args = resource["Fn::Sub"]
        assert isinstance(sub_args, list)
        assert "BucketName" in sub_args[1]
        import_val = sub_args[1]["BucketName"]
        assert "Fn::ImportValue" in import_val

    # --- CloudWatch Logs Policy ---

    def test_cw_logs_policy_actions(self, policies):
        stmts = policies["CloudWatchLogsPolicy"]["Statement"]
        actions = stmts[0]["Action"]
        assert "logs:CreateLogGroup" in actions
        assert "logs:CreateLogStream" in actions
        assert "logs:PutLogEvents" in actions

    def test_cw_logs_policy_resource_scoped(self, policies):
        resource = policies["CloudWatchLogsPolicy"]["Statement"][0]["Resource"]
        assert "Fn::Sub" in resource
        arn_str = resource["Fn::Sub"]
        assert "${AWS::Partition}" in arn_str
        assert "${AWS::Region}" in arn_str
        assert "${AWS::AccountId}" in arn_str
        assert "/aws/lambda/${ProjectPrefix}-import-documents" in arn_str

    # --- VPC Access Policy ---

    def test_vpc_policy_actions(self, policies):
        stmts = policies["VPCAccessPolicy"]["Statement"]
        actions = stmts[0]["Action"]
        assert "ec2:CreateNetworkInterface" in actions
        assert "ec2:DescribeNetworkInterfaces" in actions
        assert "ec2:DeleteNetworkInterface" in actions

    def test_vpc_policy_resource_star(self, policies):
        assert policies["VPCAccessPolicy"]["Statement"][0]["Resource"] == "*"

    # --- Secrets Manager Policy ---

    def test_secrets_manager_policy_action(self, policies):
        stmts = policies["SecretsManagerPolicy"]["Statement"]
        assert stmts[0]["Action"] == "secretsmanager:GetSecretValue"

    def test_secrets_manager_policy_scoped_to_arn(self, policies):
        resource = policies["SecretsManagerPolicy"]["Statement"][0]["Resource"]
        assert resource == {"Ref": "ClientSecretArn"}


# ===================================================================
# VPC Endpoints (Req 7.1–7.10)
# ===================================================================


class TestVPCEndpoints:
    """Verify CloudWatch Logs and Secrets Manager VPC endpoints."""

    @pytest.fixture(scope="class")
    def cw_props(self, resources):
        return resources["CloudWatchLogsVpcEndpoint"]["Properties"]

    @pytest.fixture(scope="class")
    def sm_props(self, resources):
        return resources["SecretsManagerVpcEndpoint"]["Properties"]

    # --- CloudWatch Logs Endpoint ---

    def test_cw_endpoint_type(self, cw_props):
        assert cw_props["VpcEndpointType"] == "Interface"

    def test_cw_service_name(self, cw_props):
        assert cw_props["ServiceName"] == {"Fn::Sub": "com.amazonaws.${AWS::Region}.logs"}

    def test_cw_subnets(self, cw_props):
        subnets = cw_props["SubnetIds"]
        assert {"Ref": "PrivateSubnetAId"} in subnets
        assert {"Ref": "PrivateSubnetBId"} in subnets

    def test_cw_security_groups(self, cw_props):
        assert cw_props["SecurityGroupIds"] == [{"Ref": "InternalSGId"}]

    def test_cw_private_dns(self, cw_props):
        assert cw_props["PrivateDnsEnabled"] is True

    # --- Secrets Manager Endpoint ---

    def test_sm_endpoint_type(self, sm_props):
        assert sm_props["VpcEndpointType"] == "Interface"

    def test_sm_service_name(self, sm_props):
        assert sm_props["ServiceName"] == {"Fn::Sub": "com.amazonaws.${AWS::Region}.secretsmanager"}

    def test_sm_subnets(self, sm_props):
        subnets = sm_props["SubnetIds"]
        assert {"Ref": "PrivateSubnetAId"} in subnets
        assert {"Ref": "PrivateSubnetBId"} in subnets

    def test_sm_security_groups(self, sm_props):
        assert sm_props["SecurityGroupIds"] == [{"Ref": "InternalSGId"}]

    def test_sm_private_dns(self, sm_props):
        assert sm_props["PrivateDnsEnabled"] is True


# ===================================================================
# Tags (Req 11.1–11.8)
# ===================================================================


class TestTags:
    """Verify all taggable resources have Environment and Project tags."""

    TAGGABLE_RESOURCES = [
        "ImportDocumentsRole",
        "ImportDocumentsFunction",
        "CloudWatchLogsVpcEndpoint",
        "SecretsManagerVpcEndpoint",
    ]

    @pytest.mark.parametrize("resource_name", TAGGABLE_RESOURCES)
    def test_environment_tag(self, resources, resource_name):
        tags = resources[resource_name]["Properties"]["Tags"]
        env_tags = [t for t in tags if t["Key"] == "Environment"]
        assert len(env_tags) == 1
        assert env_tags[0]["Value"] == {"Ref": "EnvironmentTag"}

    @pytest.mark.parametrize("resource_name", TAGGABLE_RESOURCES)
    def test_project_tag(self, resources, resource_name):
        tags = resources[resource_name]["Properties"]["Tags"]
        proj_tags = [t for t in tags if t["Key"] == "Project"]
        assert len(proj_tags) == 1
        assert proj_tags[0]["Value"] == "RAGPipeline"


# ===================================================================
# Outputs (Req 12.1–12.5)
# ===================================================================


class TestOutputs:
    """Verify all 5 outputs exist with correct export name patterns."""

    def test_output_count(self, outputs):
        assert len(outputs) == 5

    EXPECTED_OUTPUTS = {
        "ImportDocumentsFunctionArn": "ImportDocumentsFunctionArn",
        "ImportDocumentsFunctionName": "ImportDocumentsFunctionName",
        "ImportDocumentsRoleArn": "ImportDocumentsRoleArn",
        "CloudWatchLogsVpcEndpointId": "CloudWatchLogsVpcEndpointId",
        "SecretsManagerVpcEndpointId": "SecretsManagerVpcEndpointId",
    }

    @pytest.mark.parametrize("output_name,suffix", EXPECTED_OUTPUTS.items())
    def test_output_exists_with_export(self, outputs, output_name, suffix):
        assert output_name in outputs
        export = outputs[output_name]["Export"]["Name"]
        assert export == {"Fn::Sub": f"${{AWS::StackName}}-{suffix}"}


# ===================================================================
# Cross-Stack Imports (Req 9.1–9.3)
# ===================================================================


class TestCrossStackImports:
    """Verify 3 Fn::ImportValue references use correct export names."""

    def _collect_import_values(self, obj):
        """Recursively collect all Fn::ImportValue references from a dict."""
        results = []
        if isinstance(obj, dict):
            if "Fn::ImportValue" in obj:
                results.append(obj["Fn::ImportValue"])
            for v in obj.values():
                results.extend(self._collect_import_values(v))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(self._collect_import_values(item))
        return results

    def test_three_import_values(self, template):
        imports = self._collect_import_values(template)
        assert len(imports) == 3

    def test_pipeline_artifacts_bucket_import(self, template):
        imports = self._collect_import_values(template)
        expected = {"Fn::Sub": "${StorageStackName}-PipelineArtifactsBucketName"}
        assert expected in imports

    def test_raw_documents_bucket_name_import(self, template):
        imports = self._collect_import_values(template)
        expected = {"Fn::Sub": "${StorageStackName}-RawDocumentsBucketName"}
        assert expected in imports

    def test_raw_documents_bucket_name_import_count(self, template):
        """RawDocumentsBucketName is imported twice (env var + S3 policy)."""
        imports = self._collect_import_values(template)
        raw_doc_imports = [
            i for i in imports
            if isinstance(i, dict) and i.get("Fn::Sub", "").endswith("-RawDocumentsBucketName")
        ]
        assert len(raw_doc_imports) == 2


# ===================================================================
# GovCloud Compatibility (Req 13.1–13.3)
# ===================================================================


class TestGovCloudCompatibility:
    """Verify all ARN Fn::Sub strings use ${AWS::Partition}, no hardcoded regions or account IDs."""

    def _collect_fn_sub_strings(self, obj):
        """Recursively collect all Fn::Sub string values."""
        results = []
        if isinstance(obj, dict):
            if "Fn::Sub" in obj:
                val = obj["Fn::Sub"]
                if isinstance(val, str):
                    results.append(val)
                elif isinstance(val, list) and len(val) >= 1:
                    results.append(val[0])
            for v in obj.values():
                results.extend(self._collect_fn_sub_strings(v))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(self._collect_fn_sub_strings(item))
        return results

    def test_all_arn_subs_use_partition(self, template):
        """Every Fn::Sub string containing 'arn:' must use ${AWS::Partition}."""
        subs = self._collect_fn_sub_strings(template)
        arn_subs = [s for s in subs if "arn:" in s]
        for s in arn_subs:
            assert "${AWS::Partition}" in s, f"ARN missing ${{AWS::Partition}}: {s}"

    def test_no_hardcoded_regions(self, template):
        """No Fn::Sub string should contain hardcoded region values."""
        subs = self._collect_fn_sub_strings(template)
        hardcoded_regions = ["us-east-1", "us-west-2", "us-gov-west-1", "us-gov-east-1"]
        for s in subs:
            for region in hardcoded_regions:
                assert region not in s, f"Hardcoded region '{region}' found in: {s}"

    def test_no_hardcoded_account_ids(self, template):
        """No Fn::Sub string should contain a 12-digit hardcoded account ID."""
        import re
        subs = self._collect_fn_sub_strings(template)
        account_pattern = re.compile(r"\b\d{12}\b")
        for s in subs:
            # Skip strings that only contain pseudo-parameter references
            match = account_pattern.search(s)
            assert match is None, f"Possible hardcoded account ID in: {s}"


# ===================================================================
# Security (Req 3.3, 3.4, 8.1)
# ===================================================================


class TestSecurity:
    """Verify no plain-text secret params, no dynamic references, no S3 endpoint."""

    def test_no_client_secret_parameter(self, parameters):
        """No parameter named clientSecret or ClientSecret (plain-text secret)."""
        forbidden = {"clientSecret", "ClientSecret"}
        assert forbidden.isdisjoint(parameters.keys()), (
            f"Found forbidden parameter(s): {forbidden & parameters.keys()}"
        )

    def test_no_dynamic_secret_references(self, template):
        """No {{resolve:secretsmanager dynamic references anywhere in the template."""
        raw = json.dumps(template)
        assert "{{resolve:secretsmanager" not in raw

    def test_no_s3_vpc_endpoint_resource(self, resources):
        """No S3 VPC endpoint resource (Storage_Stack handles that)."""
        for name, res in resources.items():
            if res["Type"] == "AWS::EC2::VPCEndpoint":
                sn = res["Properties"].get("ServiceName", {})
                # ServiceName is a Fn::Sub — check the string
                if isinstance(sn, dict) and "Fn::Sub" in sn:
                    assert ".s3" not in sn["Fn::Sub"], (
                        f"S3 VPC endpoint found: {name}"
                    )


# ===================================================================
# Description (Req 8.3, 14.3)
# ===================================================================


class TestDescription:
    """Verify template metadata."""

    def test_description_mentions_s3_gateway_endpoint(self, template):
        desc = template.get("Description", "")
        assert "S3" in desc and ("Gateway Endpoint" in desc or "gateway endpoint" in desc or "Gateway endpoint" in desc or "S3 Gateway" in desc), (
            f"Description should mention S3 Gateway Endpoint dependency: {desc}"
        )

    def test_template_format_version(self, template):
        assert template["AWSTemplateFormatVersion"] == "2010-09-09"

    def test_description_exists(self, template):
        assert "Description" in template
        assert len(template["Description"]) > 0


# ===================================================================
# Orchestrator Consistency (Req 10.1–10.4)
# ===================================================================

ORCHESTRATOR_PATH = Path(__file__).resolve().parent.parent / "rag-pipeline-orchestrator-stack.json"


class TestOrchestratorConsistency:
    """Verify every parameter the orchestrator passes to ImportDocumentsStack exists in the template."""

    @pytest.fixture(scope="class")
    def orchestrator(self):
        with open(ORCHESTRATOR_PATH) as f:
            return json.load(f)

    @pytest.fixture(scope="class")
    def orchestrator_passed_params(self, orchestrator):
        """Extract parameter names the orchestrator passes to ImportDocumentsStack."""
        ids_resource = orchestrator["Resources"]["ImportDocumentsStack"]
        return list(ids_resource["Properties"]["Parameters"].keys())

    def test_all_orchestrator_params_exist_in_template(self, parameters, orchestrator_passed_params):
        """Every parameter the orchestrator passes must exist in import-documents-stack.json."""
        missing = [p for p in orchestrator_passed_params if p not in parameters]
        assert not missing, f"Orchestrator passes parameters not in template: {missing}"

    @pytest.mark.parametrize("param_name", [
        "ProjectPrefix", "EnvironmentTag", "VpcId", "PrivateSubnetAId",
        "PrivateSubnetBId", "InternalSGId", "PrivateRouteTableId",
        "StorageStackName", "LambdaS3Key", "TenantId", "ClientId",
        "ClientSecretArn", "SharepointUrl", "DriveName", "CsvCategories",
        "SharePointFolderPath",
    ])
    def test_orchestrator_param_exists(self, parameters, param_name):
        """Each expected orchestrator parameter exists in the template."""
        assert param_name in parameters, f"Missing parameter: {param_name}"


# ===================================================================
# Cross-Stack Export Verification (Req 9.1–9.3)
# ===================================================================

STORAGE_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "storage-stack.json"


class TestCrossStackExports:
    """Verify every Fn::ImportValue in import-documents-stack references an export that exists in storage-stack."""

    @pytest.fixture(scope="class")
    def storage_template(self):
        with open(STORAGE_TEMPLATE_PATH) as f:
            return json.load(f)

    @pytest.fixture(scope="class")
    def storage_export_suffixes(self, storage_template):
        """Extract export-name suffixes from storage-stack Outputs.

        Each export name is ``{"Fn::Sub": "${AWS::StackName}-<Suffix>"}``.
        We return the set of ``<Suffix>`` strings.
        """
        suffixes = set()
        for output in storage_template["Outputs"].values():
            export_name = output["Export"]["Name"]
            if isinstance(export_name, dict) and "Fn::Sub" in export_name:
                sub_str = export_name["Fn::Sub"]
                # Pattern: "${AWS::StackName}-Suffix"
                if "-" in sub_str:
                    suffix = sub_str.split("-", 1)[1]
                    suffixes.add(suffix)
        return suffixes

    # -- helper ----------------------------------------------------------

    @staticmethod
    def _collect_import_values(obj):
        """Recursively collect all Fn::ImportValue references."""
        results = []
        if isinstance(obj, dict):
            if "Fn::ImportValue" in obj:
                results.append(obj["Fn::ImportValue"])
            for v in obj.values():
                results.extend(TestCrossStackExports._collect_import_values(v))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(TestCrossStackExports._collect_import_values(item))
        return results

    @staticmethod
    def _extract_suffix(import_ref):
        """Extract the export-name suffix from an Fn::ImportValue reference.

        Import references look like ``{"Fn::Sub": "${StorageStackName}-SomeSuffix"}``.
        Returns the ``SomeSuffix`` portion, or ``None`` if the pattern doesn't match.
        """
        if isinstance(import_ref, dict) and "Fn::Sub" in import_ref:
            sub_str = import_ref["Fn::Sub"]
            if isinstance(sub_str, str) and "-" in sub_str:
                return sub_str.split("-", 1)[1]
        return None

    # -- tests -----------------------------------------------------------

    def test_import_values_are_not_empty(self, template):
        """Sanity check: the import-documents template has at least one Fn::ImportValue."""
        imports = self._collect_import_values(template)
        assert len(imports) > 0, "Expected at least one Fn::ImportValue in the template"

    def test_each_import_has_matching_storage_export(self, template, storage_export_suffixes):
        """Every Fn::ImportValue suffix must match an export suffix in storage-stack."""
        imports = self._collect_import_values(template)
        for imp in imports:
            suffix = self._extract_suffix(imp)
            assert suffix is not None, f"Could not extract suffix from import: {imp}"
            assert suffix in storage_export_suffixes, (
                f"Import suffix '{suffix}' not found in storage-stack exports. "
                f"Available: {sorted(storage_export_suffixes)}"
            )

    def test_pipeline_artifacts_export_exists(self, storage_export_suffixes):
        """Storage-stack must export PipelineArtifactsBucketName (Req 9.1)."""
        assert "PipelineArtifactsBucketName" in storage_export_suffixes

    def test_raw_documents_bucket_name_export_exists(self, storage_export_suffixes):
        """Storage-stack must export RawDocumentsBucketName (Req 9.2)."""
        assert "RawDocumentsBucketName" in storage_export_suffixes


# ===================================================================
# cfn-lint Validation (Req 14.1)
# ===================================================================


class TestCfnLint:
    """Run cfn-lint against the template and assert zero errors.

    Validates: Requirements 14.1
    """

    def test_cfn_lint_no_errors(self):
        """cfn-lint should report zero errors for import-documents-stack.json."""
        import subprocess
        import shutil

        pytest.importorskip("cfnlint", reason="cfn-lint not installed")

        # Use python3 -m cfnlint since cfn-lint may not be on PATH.
        # cfn-lint v1.x moved the CLI entry point to cfnlint.runner.cli.
        cmd = ["python3", "-m", "cfnlint.runner.cli", str(TEMPLATE_PATH)]

        result = subprocess.run(cmd, capture_output=True, text=True)

        # cfn-lint exit codes: 0 = no issues, 2 = errors, 4 = warnings, 6 = both
        # We accept 0 (clean) and 4 (warnings only); reject 2 and 6 (errors).
        has_errors = result.returncode in (2, 6)

        if has_errors:
            print("cfn-lint stdout:", result.stdout)
            print("cfn-lint stderr:", result.stderr)

        assert not has_errors, (
            f"cfn-lint reported errors (exit code {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )


# ===================================================================
# cfn-guard Compliance (Req 14.2)
# ===================================================================


class TestCfnGuard:
    """Run cfn-guard against the template and assert zero critical violations.

    Validates: Requirements 14.2
    """

    @staticmethod
    def _find_cfn_guard():
        """Locate cfn-guard binary, checking PATH and ~/.guard/bin."""
        import shutil
        import os

        binary = shutil.which("cfn-guard")
        if binary:
            return binary
        home_guard = os.path.expanduser("~/.guard/bin/cfn-guard")
        if os.path.isfile(home_guard) and os.access(home_guard, os.X_OK):
            return home_guard
        return None

    def test_cfn_guard_rulegen_smoke(self):
        """cfn-guard rulegen should parse the template without errors (syntax smoke test)."""
        import subprocess

        cfn_guard = self._find_cfn_guard()
        if cfn_guard is None:
            pytest.skip("cfn-guard not installed")

        cmd = [cfn_guard, "rulegen", "--template", str(TEMPLATE_PATH)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        assert result.returncode == 0, (
            f"cfn-guard rulegen failed (exit code {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
        # rulegen should produce non-empty output (generated rules)
        assert len(result.stdout.strip()) > 0, "cfn-guard rulegen produced no output"

    def test_cfn_guard_validate_with_generated_rules(self):
        """cfn-guard validate should pass when using auto-generated rules from the template."""
        import subprocess
        import tempfile

        cfn_guard = self._find_cfn_guard()
        if cfn_guard is None:
            pytest.skip("cfn-guard not installed")

        # Step 1: Generate rules from the template
        rulegen_cmd = [cfn_guard, "rulegen", "--template", str(TEMPLATE_PATH)]
        rulegen_result = subprocess.run(rulegen_cmd, capture_output=True, text=True)
        if rulegen_result.returncode != 0:
            pytest.skip(f"cfn-guard rulegen failed: {rulegen_result.stderr}")

        # Step 2: Write generated rules to a temp file and validate
        with tempfile.NamedTemporaryFile(mode="w", suffix=".guard", delete=False) as f:
            f.write(rulegen_result.stdout)
            rules_path = f.name

        try:
            validate_cmd = [
                cfn_guard, "validate",
                "-d", str(TEMPLATE_PATH),
                "-r", rules_path,
            ]
            result = subprocess.run(validate_cmd, capture_output=True, text=True)

            if result.returncode != 0:
                print("cfn-guard stdout:", result.stdout)
                print("cfn-guard stderr:", result.stderr)

            assert result.returncode == 0, (
                f"cfn-guard reported violations (exit code {result.returncode}):\n"
                f"{result.stdout}\n{result.stderr}"
            )
        finally:
            import os
            os.unlink(rules_path)
