import { takeOption } from './args'

export interface CliConfig {
    apiKey?: string
    host: string
    organizationId?: string
    projectId?: string
    version: number
}

const DEFAULT_HOST = 'https://us.posthog.com'
const API_KEY_ENV_NAMES = ['POSTHOG_API_KEY', 'POSTHOG_CLI_API_KEY', 'POSTHOG_CLI_TOKEN']

function firstEnv(names: string[]): string | undefined {
    for (const name of names) {
        const value = process.env[name]
        if (value) {
            return value
        }
    }
    return undefined
}

function resolveApiKey(): string | undefined {
    const name = API_KEY_ENV_NAMES.find((candidate) => process.env[candidate])
    if (!name) {
        return undefined
    }
    const trimmed = process.env[name]!.trim()
    const apiKey = (trimmed.match(/^(["'])([\s\S]*)\1$/)?.[2] ?? trimmed).trim()
    // Keep the value out of the message, because terminal output and CI logs are often shared.
    if (/[^\x21-\x7E]|["']/.test(apiKey)) {
        throw new Error(
            `The API key in ${name} contains invalid characters. Remove any spaces, quotes or line breaks inside the key, then run the command again.`
        )
    }
    return apiKey || undefined
}

function parseVersion(value: string | undefined): number {
    if (!value) {
        return 2
    }
    const parsed = Number(value)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 2
}

export function resolveCliConfig(args: string[] = []): CliConfig {
    const apiKey = resolveApiKey()
    const targetOrganizationId = takeOption(args, '--organization-id')
    const targetProjectId = takeOption(args, '--project-id')
    const hasTarget = targetOrganizationId !== undefined || targetProjectId !== undefined
    if (targetOrganizationId === '' || targetProjectId === '') {
        throw new Error('Project and organization IDs must not be empty.')
    }
    const organizationId = hasTarget
        ? targetOrganizationId
        : firstEnv(['POSTHOG_ORGANIZATION_ID', 'POSTHOG_CLI_ORGANIZATION_ID'])
    const projectId = hasTarget
        ? targetProjectId
        : firstEnv(['POSTHOG_PROJECT_ID', 'POSTHOG_CLI_PROJECT_ID', 'POSTHOG_CLI_ENV_ID'])

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
