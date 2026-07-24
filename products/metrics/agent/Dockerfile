# PostHog metrics agent: scrapes Prometheus /metrics endpoints in your infra
# and forwards them to PostHog as OTLP metrics (exemplars included).
#
# The upstream collector image has no shell, so the collector binary is
# re-based onto alpine to support the config-rendering entrypoint.
# Keep the collector version in sync with tests/integration/docker-compose.yml.
FROM otel/opentelemetry-collector-contrib:0.142.0@sha256:38c349c3b7a2fd7ea46700cde8fa13d35b699ef2ce245bdf34dae2a413512f76 AS collector

FROM alpine:3.21@sha256:48b0309ca019d89d40f670aa1bc06e426dc0931948452e8491e3d65087abc07d
RUN apk add --no-cache ca-certificates && adduser -D -u 10001 otel
COPY --from=collector /otelcol-contrib /usr/local/bin/otelcol-contrib
COPY config/config.yaml.tmpl /etc/posthog/config.yaml.tmpl
COPY entrypoint.sh /entrypoint.sh
USER 10001
EXPOSE 13133
ENTRYPOINT ["/entrypoint.sh"]
