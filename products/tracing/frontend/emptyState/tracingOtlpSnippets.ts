export type TracingSetupPlatform = 'sdk' | 'collector' | 'kubernetes' | 'docker'

export interface TracingSnippetParams {
    token: string
    host: string
    environment: string
}

export const TRACING_SETUP_PLATFORMS: { key: TracingSetupPlatform; label: string }[] = [
    { key: 'sdk', label: 'OpenTelemetry SDK' },
    { key: 'collector', label: 'OTel Collector' },
    { key: 'kubernetes', label: 'Kubernetes' },
    { key: 'docker', label: 'Docker' },
]

/**
 * Keeps the environment to characters that need no escaping in `OTEL_RESOURCE_ATTRIBUTES`,
 * YAML, or a shell, where a comma or a quote would split or break the snippet. It runs on
 * every keystroke, so a space becomes a hyphen rather than being trimmed away mid-word.
 */
export function normalizeEnvironment(value: string): string {
    return value.replace(/\s+/g, '-').replace(/[^A-Za-z0-9._-]/g, '')
}

function envVars({ token, host, environment }: TracingSnippetParams): [string, string][] {
    const vars: [string, string][] = [
        ['OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', `${host}/i/v1/traces`],
        ['OTEL_EXPORTER_OTLP_TRACES_HEADERS', `Authorization=Bearer ${token}`],
        ['OTEL_EXPORTER_OTLP_TRACES_PROTOCOL', 'http/protobuf'],
        ['OTEL_SERVICE_NAME', 'my-service'],
    ]
    if (environment) {
        vars.push(['OTEL_RESOURCE_ATTRIBUTES', `deployment.environment.name=${environment}`])
    }
    return vars
}

function collectorSnippet({ token, host, environment }: TracingSnippetParams): string {
    const processors = environment
        ? [
              'processors:',
              '  batch:',
              '  resource/environment:',
              '    attributes:',
              '      - key: deployment.environment.name',
              `        value: "${environment}"`,
              '        action: upsert',
          ]
        : ['processors:', '  batch:']
    return [
        '# Listens on all interfaces so apps on other',
        '# hosts can reach it. For a sidecar or same-host',
        '# Collector, use localhost. Otherwise, restrict',
        '# access with your network rules.',
        'receivers:',
        '  otlp:',
        '    protocols:',
        '      http:',
        '        endpoint: 0.0.0.0:4318',
        '      grpc:',
        '        endpoint: 0.0.0.0:4317',
        '',
        ...processors,
        '',
        'exporters:',
        '  otlphttp/posthog:',
        `    traces_endpoint: "${host}/i/v1/traces"`,
        '    headers:',
        `      Authorization: "Bearer ${token}"`,
        '',
        'service:',
        '  pipelines:',
        '    traces:',
        '      receivers: [otlp]',
        `      processors: [${environment ? 'resource/environment, batch' : 'batch'}]`,
        '      exporters: [otlphttp/posthog]',
    ].join('\n')
}

function kubernetesSnippet(params: TracingSnippetParams): string {
    return [
        '# In your Deployment, under spec.template.spec.containers[]:',
        'env:',
        ...envVars(params).flatMap(([name, value]) => [`  - name: ${name}`, `    value: "${value}"`]),
    ].join('\n')
}

function dockerSnippet(params: TracingSnippetParams): string {
    return [
        'docker run -d \\',
        ...envVars(params).map(([name, value]) => `  -e ${name}="${value}" \\`),
        '  your-app-image',
    ].join('\n')
}

function sdkSnippet(params: TracingSnippetParams): string {
    return envVars(params)
        .map(([name, value]) => `export ${name}="${value}"`)
        .join('\n')
}

export function buildTracingSnippet(platform: TracingSetupPlatform, params: TracingSnippetParams): string {
    switch (platform) {
        case 'collector':
            return collectorSnippet(params)
        case 'kubernetes':
            return kubernetesSnippet(params)
        case 'docker':
            return dockerSnippet(params)
        case 'sdk':
            return sdkSnippet(params)
    }
}
