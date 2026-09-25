import re
from pathlib import Path
from urllib.parse import quote, urlencode

TEMPLATE_PATH = Path(__file__).with_name("aws_firehose_template.yaml")

# Matches an AWS region name in any partition, e.g. us-east-1, eu-central-2, us-gov-west-1, cn-north-1.
AWS_REGION_RE = r"^[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-\d$"

FIREHOSE_ENDPOINT_PATH = "/i/v1/logs/aws/firehose"

# Firehose buffering that keeps one request under capture-logs' body limit once CloudWatch's
# gzip output is base64-encoded, while still delivering within about a minute.
FIREHOSE_BUFFER_SIZE_MB = 1
FIREHOSE_BUFFER_INTERVAL_SECONDS = 60
FIREHOSE_RETRY_DURATION_SECONDS = 300

STACK_NAME_ID_LENGTH = 8
# CloudFormation caps a stack name at 128, less the id fragment and the hyphen before it.
STACK_NAME_PREFIX_MAX_LENGTH = 128 - STACK_NAME_ID_LENGTH - 1

# Only the customer knows which log group to stream, so the link carries a placeholder for it.
# Leaving it incomplete also stops the link being opened without being read.
LOG_GROUP_PLACEHOLDER = "{your-log-group-name}"


def stack_name_for(source_name: str, source_id: str) -> str:
    # CloudFormation stack names allow letters, digits and hyphens, and must start with a letter.
    # The id fragment keeps two sources with the same name from colliding in one account.
    slug = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9-]+", "-", source_name)).strip("-").lower()
    prefix = f"posthog-logs-{slug or 'source'}"[:STACK_NAME_PREFIX_MAX_LENGTH].rstrip("-")
    return f"{prefix}-{source_id[:STACK_NAME_ID_LENGTH]}"


def console_host(region: str) -> str | None:
    """Console hostname for the region's partition; None for regions without a public console."""
    if not re.match(AWS_REGION_RE, region):
        return None
    if "-iso" in region:
        return None
    if region.startswith("us-gov-"):
        return f"{region}.console.amazonaws-us-gov.com"
    if region.startswith("cn-"):
        return f"{region}.console.amazonaws.cn"
    return f"{region}.console.aws.amazon.com"


def quick_create_url(
    *, region: str, template_url: str, endpoint_url: str, access_key: str, source_name: str, source_id: str
) -> str | None:
    """CloudFormation quick-create link, or None when the region has no public console or no
    template has been published."""
    host = console_host(region)
    if host is None or not template_url:
        return None
    params = urlencode(
        {
            "templateURL": template_url,
            "stackName": stack_name_for(source_name, source_id),
            "param_PostHogEndpointUrl": endpoint_url,
            "param_PostHogAccessKey": access_key,
            "param_LogGroupName": LOG_GROUP_PLACEHOLDER,
            "param_BufferSizeMB": str(FIREHOSE_BUFFER_SIZE_MB),
            "param_BufferIntervalSeconds": str(FIREHOSE_BUFFER_INTERVAL_SECONDS),
            "param_RetryDurationSeconds": str(FIREHOSE_RETRY_DURATION_SECONDS),
        },
        # Leave `{}` unencoded so the log-group placeholder stays readable in the link.
        quote_via=lambda value, *_: quote(value, safe="{}"),
    )
    return f"https://{host}/cloudformation/home?region={region}#/stacks/quickcreate?{params}"
