export interface CliConfig {
    apiKey?: string
    host: string
    organizationId?: string
    projectId?: string
    version: number
}

const DEFAULT_HOST = 'https://us.posthog.com'

const HOST_ENV_NAMES = ['POSTHOG_HOST', 'POSTHOG_CLI_HOST']

function firstEnvEntry(names: string[]): { name: string; value: string } | undefined {
    for (const name of names) {
        const value = process.env[name]
        if (value) {
            return { name, value }
        }
    }
    return undefined
}

function firstEnv(names: string[]): string | undefined {
    return firstEnvEntry(names)?.value
}

// Users often set the host without a scheme (`us.posthog.com`), which makes every request URL relative.
function normalizeHost(value: string, source: string): string {
    const trimmed = value.trim()
    const withScheme = /^[a-z][a-z\d+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`
    let url: URL
    try {
        url = new URL(withScheme)
    } catch {
        throw new Error(`Invalid PostHog host "${value}" in ${source}. Use a full URL, such as https://us.posthog.com.`)
    }
    if (url.protocol !== 'https:' && url.protocol !== 'http:') {
        throw new Error(`Invalid PostHog host "${value}" in ${source}. The URL must start with https:// or http://.`)
    }
    return withScheme.replace(/\/+$/, '')
}

function resolveHost(): string {
    const entry = firstEnvEntry(HOST_ENV_NAMES)
    return entry ? normalizeHost(entry.value, entry.name) : DEFAULT_HOST
}

function parseVersion(value: string | undefined): number {
    if (!value) {
        return 2
    }
    const parsed = Number(value)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 2
}

export function resolveCliConfig(): CliConfig {
    const apiKey = firstEnv(['POSTHOG_API_KEY', 'POSTHOG_CLI_API_KEY', 'POSTHOG_CLI_TOKEN'])
    const organizationId = firstEnv(['POSTHOG_ORGANIZATION_ID', 'POSTHOG_CLI_ORGANIZATION_ID'])
    const projectId = firstEnv(['POSTHOG_PROJECT_ID', 'POSTHOG_CLI_PROJECT_ID', 'POSTHOG_CLI_ENV_ID'])

    return {
        host: resolveHost(),
        version: parseVersion(firstEnv(['POSTHOG_MCP_VERSION', 'POSTHOG_CLI_MCP_VERSION'])),
        ...(apiKey ? { apiKey } : {}),
        ...(organizationId ? { organizationId } : {}),
        ...(projectId ? { projectId } : {}),
    }
}

export function requireApiKey(config: CliConfig): string {
    if (!config.apiKey) {
        throw new Error(
            'Missing PostHog API key. Run `posthog-cli login` or set POSTHOG_CLI_API_KEY and POSTHOG_CLI_PROJECT_ID.'
        )
    }
    return config.apiKey
}
