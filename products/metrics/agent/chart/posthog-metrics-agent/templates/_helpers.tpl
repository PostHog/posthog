{{- define "posthog-metrics-agent.fullname" -}}
{{- if contains .Chart.Name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "posthog-metrics-agent.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "posthog-metrics-agent.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "posthog-metrics-agent.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "posthog-metrics-agent.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- /* Never fall back to the namespace's shared `default` account: the chart's
      ClusterRole would leak to every workload already using it. */}}
{{- required "serviceAccount.name is required when serviceAccount.create is false" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "posthog-metrics-agent.secretName" -}}
{{- if .Values.posthog.existingSecret }}
{{- .Values.posthog.existingSecret }}
{{- else }}
{{- include "posthog-metrics-agent.fullname" . }}
{{- end }}
{{- end }}

{{/*
The full collector config mounted at /etc/posthog/config.yaml (the image
entrypoint's full-override escape hatch). The API key is referenced as
${env:POSTHOG_API_KEY} and resolved by the collector from the pod env,
so it never appears in the ConfigMap.
*/}}
{{- define "posthog-metrics-agent.collectorConfig" -}}
{{- if and (not .Values.scrape.annotationDiscovery) (not .Values.scrape.staticTargets) (not .Values.scrape.extraScrapeConfigs) }}
{{- fail "at least one of scrape.annotationDiscovery, scrape.staticTargets or scrape.extraScrapeConfigs must be set" }}
{{- end }}
receivers:
    prometheus:
        config:
            scrape_configs:
{{- if .Values.scrape.annotationDiscovery }}
                - job_name: kubernetes-pods
                  scrape_interval: {{ .Values.scrape.interval }}
                  # OpenMetrics first so exemplars (trace links) survive the scrape.
                  scrape_protocols: [OpenMetricsText1.0.0, OpenMetricsText0.0.1, PrometheusText0.0.4]
                  kubernetes_sd_configs:
                      - role: pod
                  relabel_configs:
                      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
                        action: keep
                        regex: 'true'
                      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
                        action: replace
                        regex: (.+)
                        target_label: __metrics_path__
                      - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
                        action: replace
                        regex: ([^:]+)(?::\d+)?;(\d+)
                        replacement: $$1:$$2
                        target_label: __address__
                      - source_labels: [__meta_kubernetes_namespace]
                        action: replace
                        target_label: namespace
                      - source_labels: [__meta_kubernetes_pod_name]
                        action: replace
                        target_label: pod
{{- end }}
{{- if .Values.scrape.staticTargets }}
                - job_name: static-targets
                  scrape_interval: {{ .Values.scrape.interval }}
                  # OpenMetrics first so exemplars (trace links) survive the scrape.
                  scrape_protocols: [OpenMetricsText1.0.0, OpenMetricsText0.0.1, PrometheusText0.0.4]
                  static_configs:
                      - targets: [{{ range $i, $t := .Values.scrape.staticTargets }}{{ if $i }}, {{ end }}'{{ $t }}'{{ end }}]
{{- end }}
{{- with .Values.scrape.extraScrapeConfigs }}
{{ tpl . $ | indent 16 }}
{{- end }}

processors:
    # Shed load instead of buffering unbounded memory when PostHog is unreachable.
    memory_limiter:
        check_interval: 1s
        limit_mib: 512
        spike_limit_mib: 128
    batch:

exporters:
    otlphttp:
        # The otlphttp exporter appends /v1/metrics to `endpoint`, but PostHog's
        # public ingest route is /i/v1/metrics, so pin the per-signal path.
        metrics_endpoint: '{{ .Values.posthog.host }}/i/v1/metrics'
        compression: gzip
        headers:
            authorization: 'Bearer ${env:POSTHOG_API_KEY}'
        retry_on_failure:
            enabled: true

extensions:
    health_check:
        endpoint: 0.0.0.0:13133

service:
    extensions: [health_check]
    pipelines:
        metrics:
            receivers: [prometheus]
            processors: [memory_limiter, batch]
            exporters: [otlphttp]
{{- end }}
