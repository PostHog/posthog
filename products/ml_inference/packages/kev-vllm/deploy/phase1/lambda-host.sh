#!/usr/bin/env bash
# Drive a hand-launched decision instance from an engineer's machine in one go: the SSH key and the CA key come from
# 1Password, the checkpoint reaches the box through presigned URLs, the box's certificate is signed here from a CSR
# the box made (its private key never leaves it), and the bearer comes from the gateway's secrets bag. Secrets
# travel over the SSH session, never through a command line or a file on this machine.
#
#   deploy/phase1/lambda-host.sh prod-us all
#
# The first argument names the environment: its values live in envs/<environment>.env (see envs/prod-us.env.example),
# with the SSH key and the CA key as op:// references. The script re-executes itself under `op run --env-file` so
# 1Password prompts once. Steps: `sync` copies this directory to the box, `stage` downloads and verifies the
# checkpoint, `certificate` issues the box its certificate, `bootstrap` writes /etc/kev-vllm/env and runs
# bootstrap.sh, `all` does the four.
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
INSTANCE_IP=${TARGET#*@}
CERT_DAYS=1826
: "${LAMBDA_SSH_KEY:?private key from 1Password (op run resolves it)}"

# Secretive pins IdentityAgent in ssh config, so the throwaway agent has to be named explicitly.
eval "$(ssh-agent -s)" >/dev/null
trap 'ssh-agent -k >/dev/null 2>&1' EXIT
printf '%s\n' "$LAMBDA_SSH_KEY" | ssh-add -q - 2>/dev/null
SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o "IdentityAgent=$SSH_AUTH_SOCK" -o IdentitiesOnly=no)

secret_fields() {
  local profile=$1 secret_id=$2; shift 2
  aws secretsmanager get-secret-value --profile "$profile" --secret-id "$secret_id" --query SecretString --output text \
    | python3 -c 'import json, sys; bag = json.load(sys.stdin); print(*(bag[field] for field in sys.argv[1:]), sep="\n")' "$@"
}

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

issue_certificate() {
  : "${KEV_CA_KEY:?CA private key from 1Password (op run resolves it)}"
  # The box keeps its private key and hands back a CSR; the CA key touches this machine only inside a private
  # temporary directory for the signing call. Five years of validity, so nothing on the box ever renews.
  local csr signing_dir
  csr=$("${SSH[@]}" "$TARGET" "set -e; sudo install -d -m 0750 /etc/kev-vllm/tls
    [ -f /etc/kev-vllm/tls/instance.key ] || sudo sh -c 'umask 077; openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out /etc/kev-vllm/tls/instance.key'
    sudo openssl req -new -key /etc/kev-vllm/tls/instance.key -subj '/O=PostHog/CN=$INSTANCE_IP'")
  signing_dir=$(mktemp -d)
  trap 'rm -rf "$signing_dir"; ssh-agent -k >/dev/null 2>&1' EXIT
  chmod 700 "$signing_dir"
  printf '%s\n' "$KEV_CA_KEY" > "$signing_dir/ca.key"
  printf 'subjectAltName=IP:%s\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature\nbasicConstraints=CA:FALSE\n' "$INSTANCE_IP" > "$signing_dir/ext"
  printf '%s\n' "$csr" | openssl x509 -req -CA "$HERE/ca.pem" -CAkey "$signing_dir/ca.key" -days "$CERT_DAYS" -extfile "$signing_dir/ext" -out "$signing_dir/instance.crt" 2>/dev/null
  rm -f "$signing_dir/ca.key"
  openssl x509 -in "$signing_dir/instance.crt" -noout -subject -enddate
  tar -C "$signing_dir" -cf - instance.crt | "${SSH[@]}" "$TARGET" "sudo tar -C /etc/kev-vllm/tls -xf - && sudo chmod 0644 /etc/kev-vllm/tls/instance.crt"
  "${SSH[@]}" "$TARGET" "sudo tee /etc/kev-vllm/tls/ca.pem >/dev/null && sudo chmod 0644 /etc/kev-vllm/tls/ca.pem" < "$HERE/ca.pem"
  rm -rf "$signing_dir"
}

bootstrap_box() {
  : "${GATEWAY_SECRETS_PROFILE:?}" "${MODEL_NAME:?}" "${IMAGE:?}"
  local bearer
  # The gateway reads the same bag, so the two sides of the bearer cannot drift.
  read -r bearer < <(secret_fields "$GATEWAY_SECRETS_PROFILE" ai-gateway-secrets AI_GATEWAY_KEV_API_KEY)
  # The env file goes over stdin and lands root-only on the box; bootstrap.sh reads it from there.
  printf '%s\n' \
    "INSTANCE_IP=$INSTANCE_IP" \
    "KEV_BEARER=$bearer" \
    "IMAGE=$IMAGE" \
    "MODEL_DIR=/srv/models/${MODEL_NAME}" \
    "KEV_DATE_FACTS=${KEV_DATE_FACTS:-0}" \
    | "${SSH[@]}" "$TARGET" "set -e; sudo install -d -m 0750 /etc/kev-vllm; sudo bash -c 'umask 077; cat > /etc/kev-vllm/env'; sudo kev-vllm-phase1/bootstrap.sh"
}

case "$STEP" in
  sync) sync_files ;;
  stage) stage_checkpoint ;;
  certificate) issue_certificate ;;
  bootstrap) sync_files; bootstrap_box ;;
  all) sync_files; stage_checkpoint; issue_certificate; bootstrap_box ;;
  *) echo "unknown step $STEP (sync, stage, certificate, bootstrap, all)" >&2; exit 2 ;;
esac
