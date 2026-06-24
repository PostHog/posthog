export interface CliConfig {
    apiKey?: string
    host: string
    organizationId?: string
    projectId?: string
    version: number
}

const DEFAULT_HOST = 'https://us.posthog.com'

function firstEnv(names: string[]): string | undefined {
    for (const name of names) {
        const value = process.env[name]
        if (value) {
            return value
        }
    }
    return undefined
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
        host: firstEnv(['POSTHOG_HOST', 'POSTHOG_CLI_HOST']) ?? DEFAULT_HOST,
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
