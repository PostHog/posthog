#!/usr/bin/env bash
# Drive a hand-launched decision instance from an engineer's machine in one go: the SSH key comes from 1Password into
# a throwaway agent, the checkpoint reaches the box through presigned URLs, and the secrets the box needs travel over
# the SSH session, never through a command line or a file on this machine.
#
#   deploy/phase1/lambda-host.sh prod-us all
#
# The first argument names the environment: its values live in envs/<environment>.env (see envs/prod-us.env.example),
# with secrets as op:// references. The script re-executes itself under `op run --env-file` so 1Password resolves
# them once. Steps: `sync` copies this directory to the box, `stage` downloads and verifies the checkpoint,
# `bootstrap` writes /etc/kev-vllm/env and runs bootstrap.sh, `all` does the three.
set -euo pipefail

ENVIRONMENT=${1:?environment, one of the files under envs/ without the .env suffix}
STEP=${2:-all}
HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE="$HERE/envs/$ENVIRONMENT.env"
[ -f "$ENV_FILE" ] || { echo "no $ENV_FILE; copy envs/$ENVIRONMENT.env.example and fill it in" >&2; exit 2; }
if [ -z "${LAMBDA_HOST_RESOLVED:-}" ]; then
  exec op run --env-file "$ENV_FILE" -- env LAMBDA_HOST_RESOLVED=1 "$0" "$@"
fi
TARGET=${TARGET:?TARGET in $ENV_FILE}
: "${LAMBDA_SSH_KEY:?private key from 1Password (op run resolves it)}"

# Secretive pins IdentityAgent in ssh config, so the throwaway agent has to be named explicitly.
eval "$(ssh-agent -s)" >/dev/null
trap 'ssh-agent -k >/dev/null 2>&1' EXIT
printf '%s\n' "$LAMBDA_SSH_KEY" | ssh-add -q - 2>/dev/null
SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o "IdentityAgent=$SSH_AUTH_SOCK" -o IdentitiesOnly=no)

sync_files() {
  rsync -az -e "${SSH[*]}" --exclude 'envs' "$HERE/" "$TARGET:kev-vllm-phase1/"
  echo "synced deploy files"
}

stage_checkpoint() {
  : "${BASE_MODELS_BUCKET:?}" "${AWS_READ_PROFILE:?}" "${MODEL_NAME:?}" "${MODEL_VERSION:?}" "${IMAGE:?}"
  local prefix="posthog/${MODEL_NAME}-vllm/${MODEL_VERSION}"
  local dest="/srv/models/${MODEL_NAME}"
  # One presigned URL per object, valid for half an hour; the box needs no AWS credential to fetch them.
  local listing
  listing=$(aws s3 ls "s3://${BASE_MODELS_BUCKET}/${prefix}/" --recursive --profile "$AWS_READ_PROFILE" | awk '{print $4}')
  [ -n "$listing" ] || { echo "nothing under s3://${BASE_MODELS_BUCKET}/${prefix}/" >&2; exit 1; }
  {
    while IFS= read -r key; do
      printf '%s\t%s\n' "${key#"$prefix"/}" "$(aws s3 presign "s3://${BASE_MODELS_BUCKET}/${key}" --expires-in 1800 --profile "$AWS_READ_PROFILE")"
    done <<< "$listing"
  } | "${SSH[@]}" "$TARGET" "set -e; sudo mkdir -p '$dest' && sudo chown \"\$USER\" '$dest'; cd '$dest'
    while IFS=\$'\t' read -r name url; do
      mkdir -p \"\$(dirname \"\$name\")\"
      [ -f \"\$name\" ] || curl -fsSL --retry 5 --retry-all-errors -o \"\$name\" \"\$url\"
    done
    sudo chmod -R a+rX /srv/models
    sudo docker pull -q '$IMAGE' >/dev/null
    sudo docker run --rm -v '$dest':/models/kev-4b:ro --entrypoint kev-vllm-checkpoint '$IMAGE' verify /models/kev-4b"
}

bootstrap_box() {
  : "${INSTANCE_HOST:?}" "${ACME_EMAIL:?}" "${ROUTE53_ZONE_ID:?}" "${AWS_ACCESS_KEY_ID:?}" "${AWS_SECRET_ACCESS_KEY:?}"
  : "${KEV_BEARER:?}" "${MODEL_NAME:?}" "${IMAGE:?}"
  # The env file goes over stdin and lands root-only on the box; bootstrap.sh reads it from there.
  printf '%s\n' \
    "INSTANCE_HOST=$INSTANCE_HOST" \
    "ACME_EMAIL=$ACME_EMAIL" \
    "ROUTE53_ZONE_ID=$ROUTE53_ZONE_ID" \
    "AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID" \
    "AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY" \
    "AWS_REGION=${AWS_REGION:-us-east-1}" \
    "KEV_BEARER=$KEV_BEARER" \
    "IMAGE=$IMAGE" \
    "MODEL_DIR=/srv/models/${MODEL_NAME}" \
    "KEV_DATE_FACTS=${KEV_DATE_FACTS:-0}" \
    | "${SSH[@]}" "$TARGET" "set -e; sudo install -d -m 0750 /etc/kev-vllm; sudo bash -c 'umask 077; cat > /etc/kev-vllm/env'; sudo kev-vllm-phase1/bootstrap.sh"
}

case "$STEP" in
  sync) sync_files ;;
  stage) stage_checkpoint ;;
  bootstrap) sync_files; bootstrap_box ;;
  all) sync_files; stage_checkpoint; bootstrap_box ;;
  *) echo "unknown step $STEP (sync, stage, bootstrap, all)" >&2; exit 2 ;;
esac
