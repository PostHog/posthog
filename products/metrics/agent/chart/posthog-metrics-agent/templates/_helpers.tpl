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
{{/*
Hashmod pair appended to every generated scrape job when shards > 1: each
pod keeps only targets hashing to its SHARD_INDEX (exported by the image
entrypoint from the StatefulSet pod ordinal). Runs last so it hashes the
final __address__, after the annotation port rewrite.
*/}}
{{- define "posthog-metrics-agent.shardRelabel" -}}
- source_labels: [__address__]
  modulus: {{ int .Values.shards }}
  target_label: __tmp_shard
  action: hashmod
- source_labels: [__tmp_shard]
  regex: '${env:SHARD_INDEX}'
  action: keep
{{- end }}

{{- define "posthog-metrics-agent.collectorConfig" -}}
{{- $scrape := or .Values.scrape.annotationDiscovery .Values.scrape.staticTargets .Values.scrape.extraScrapeConfigs }}
{{- $gcp := .Values.gcp.projectId }}
{{- if and (not $scrape) (not $gcp) }}
{{- fail "at least one of scrape.annotationDiscovery, scrape.staticTargets, scrape.extraScrapeConfigs or gcp.projectId must be set" }}
{{- end }}
{{- if and $gcp (gt (int .Values.shards) 1) }}
{{- fail "gcp.projectId cannot be combined with shards > 1: every shard would pull the same Cloud Monitoring series. Run a separate release for Google Cloud Monitoring" }}
{{- end }}
{{- if and $gcp (not .Values.gcp.metrics) (not .Values.gcp.metricFilters) }}
{{- fail "gcp.metrics or gcp.metricFilters is required when gcp.projectId is set" }}
{{- end }}
receivers:
{{- if $scrape }}
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
{{- if gt (int .Values.shards) 1 }}
{{- include "posthog-metrics-agent.shardRelabel" . | nindent 22 }}
{{- end }}
{{- end }}
{{- if .Values.scrape.staticTargets }}
                - job_name: static-targets
                  scrape_interval: {{ .Values.scrape.interval }}
                  # OpenMetrics first so exemplars (trace links) survive the scrape.
                  scrape_protocols: [OpenMetricsText1.0.0, OpenMetricsText0.0.1, PrometheusText0.0.4]
                  static_configs:
                      - targets: [{{ range $i, $t := .Values.scrape.staticTargets }}{{ if $i }}, {{ end }}'{{ $t }}'{{ end }}]
{{- if gt (int .Values.shards) 1 }}
                  relabel_configs:
{{- include "posthog-metrics-agent.shardRelabel" . | nindent 22 }}
{{- end }}
{{- end }}
{{- with .Values.scrape.extraScrapeConfigs }}
{{ tpl . $ | indent 16 }}
{{- end }}
{{- end }}
{{- if $gcp }}
    googlecloudmonitoring:
        project_id: {{ .Values.gcp.projectId }}
        collection_interval: {{ .Values.gcp.collectionInterval }}
        metrics_list:
{{- range .Values.gcp.metrics }}
            - metric_name: '{{ . | replace "'" "''" }}'
{{- end }}
{{- range .Values.gcp.metricFilters }}
            - metric_descriptor_filter: '{{ . | replace "'" "''" }}'
{{- end }}
{{- end }}

processors:
    # Shed load instead of buffering unbounded memory when PostHog is unreachable.
    memory_limiter:
        check_interval: 1s
        limit_mib: 512
        spike_limit_mib: 128
    batch:
{{- if $gcp }}
    # Cloud Monitoring resources carry no service.name; give them one so they
    # group in the Metrics UI. `insert` never overrides a scraped job_name.
    resource/gcp:
        attributes:
            - key: service.name
              value: '{{ .Values.gcp.serviceName | default "google-cloud-monitoring" | replace "'" "''" }}'
              action: insert
{{- end }}

exporters:
    otlphttp:
        # The otlphttp exporter appends /v1/metrics to `endpoint`, but PostHog's
        # public ingest route is /i/v1/metrics, so pin the per-signal path.
        metrics_endpoint: '{{ .Values.posthog.host }}{{ .Values.posthog.ingestPath | default "/i/v1/metrics" }}'
        compression: gzip
        headers:
            authorization: 'Bearer ${env:POSTHOG_API_KEY}'
        {{- if .Values.persistence.enabled }}
        # Persist undelivered batches so a restart during an outage loses nothing.
        sending_queue:
            enabled: true
            storage: file_storage
        {{- end }}
        retry_on_failure:
            enabled: true

extensions:
    health_check:
        endpoint: 0.0.0.0:13133
    {{- if .Values.persistence.enabled }}
    file_storage:
        directory: /var/lib/posthog-agent
        create_directory: true
    {{- end }}

service:
    # Expose the collector's own metrics (scrape health, queue depth, drops)
    # on :8888 so the agent is self-observable, the way vmagent exposes its.
    telemetry:
        metrics:
            readers:
                - pull:
                      exporter:
                          prometheus:
                              host: 0.0.0.0
                              port: 8888
    extensions: [health_check{{ if .Values.persistence.enabled }}, file_storage{{ end }}]
    pipelines:
        metrics:
            receivers: [{{ if $scrape }}prometheus{{ end }}{{ if and $scrape $gcp }}, {{ end }}{{ if $gcp }}googlecloudmonitoring{{ end }}]
            processors: [memory_limiter, {{ if $gcp }}resource/gcp, {{ end }}batch]
            exporters: [otlphttp]
{{- end }}
