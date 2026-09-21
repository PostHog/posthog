import re
from pathlib import Path
from urllib.parse import quote, urlencode

TEMPLATE_PATH = Path(__file__).with_name("aws_firehose_template.yaml")

# Matches every commercial, GovCloud and isolated AWS region name, e.g. us-east-1, eu-central-2, us-gov-west-1.
AWS_REGION_RE = r"^[a-z]{2}(-gov|-iso[a-z]*)?-[a-z]+-\d$"

FIREHOSE_ENDPOINT_PATH = "/i/v1/logs/aws/firehose"

# Firehose buffering that keeps one request under capture-logs' body limit once CloudWatch's
# gzip output is base64-encoded, while still delivering within about a minute.
FIREHOSE_BUFFER_SIZE_MB = 1
FIREHOSE_BUFFER_INTERVAL_SECONDS = 60
FIREHOSE_RETRY_DURATION_SECONDS = 300

STACK_NAME_MAX_LENGTH = 128
STACK_NAME_ID_LENGTH = 8

# Only the customer knows which log group to stream, so the link carries a placeholder for it.
# Leaving the link deliberately incomplete also stops it being opened without being read, which
# matters while no template has been deployed from this stack yet.
LOG_GROUP_PLACEHOLDER = "{your-log-group-name}"


def _quote_keeping_placeholders(value: str, safe: str, encoding: str, errors: str) -> str:
    """Percent-encode a query value but leave `{}` alone, so the placeholder stays readable."""
    return quote(str(value), safe="{}")


def stack_name_for(source_name: str, source_id: str) -> str:
    # CloudFormation stack names allow letters, digits and hyphens, and must start with a letter.
    # The id fragment keeps two sources with the same name from colliding in one account.
    slug = re.sub(r"[^A-Za-z0-9-]+", "-", source_name).strip("-").lower()
    prefix = f"posthog-logs-{slug or 'source'}"[: STACK_NAME_MAX_LENGTH - STACK_NAME_ID_LENGTH - 1].rstrip("-")
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
    """CloudFormation quick-create link, shown as a value to read and edit rather than a button.
    The log group is a placeholder, so the customer fills it in before the link resolves to a
    stack. Nothing is created until they click Create stack in their own console."""
    host = console_host(region)
    if host is None:
        return None
    params = urlencode(
        {
            "templateURL": template_url,
            "stackName": stack_name_for(source_name, source_id),
            "param_PostHogEndpointUrl": endpoint_url,
            "param_PostHogAccessKey": access_key,
            "param_LogGroupName": LOG_GROUP_PLACEHOLDER,
            "param_BufferSizeMB": FIREHOSE_BUFFER_SIZE_MB,
            "param_BufferIntervalSeconds": FIREHOSE_BUFFER_INTERVAL_SECONDS,
            "param_RetryDurationSeconds": FIREHOSE_RETRY_DURATION_SECONDS,
        },
        quote_via=_quote_keeping_placeholders,
    )
    return f"https://{host}/cloudformation/home?region={region}#/stacks/quickcreate?{params}"
