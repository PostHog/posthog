#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
    echo "Usage: $0 [--region us|eu|all]"
    echo ""
    echo "Deploy GLM-5 inference on Modal."
    echo ""
    echo "Options:"
    echo "  --region   Region to deploy to (us, eu, or all). Default: all"
    exit 1
}

REGION="all"
while [[ $# -gt 0 ]]; do
    case $1 in
        --region) REGION="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

deploy_region() {
    local region=$1
    echo "==> Deploying GLM-5 to ${region}..."
    REGION="${region}" modal deploy "${SCRIPT_DIR}/glm5_serving.py"
    echo "==> ${region} deployment complete"
}

case "${REGION}" in
    us)  deploy_region us ;;
    eu)  deploy_region eu ;;
    all)
        deploy_region us
        deploy_region eu
        ;;
    *)   echo "Invalid region: ${REGION}"; usage ;;
esac

echo ""
echo "Done. Set the following env vars on the LLM Gateway:"
echo "  LLM_GATEWAY_GLM5_API_BASE_URL_US=<us-deployment-url>"
echo "  LLM_GATEWAY_GLM5_API_BASE_URL_EU=<eu-deployment-url>"
