export interface CliConfig {
    apiKey?: string
    host: string
    organizationId?: string
    projectId?: string
    version: number
}

const DEFAULT_HOST = 'https://us.posthog.com'

function firstEnv(names: string[]): string | undefined {
    return firstEnvEntry(names)?.value
}

interface EnvEntry {
    name: string
    value: string
}

function firstEnvEntry(names: string[]): EnvEntry | undefined {
    for (const name of names) {
        const value = process.env[name]
        if (value) {
            return { name, value }
        }
    }
    return undefined
}

/**
 * Shell-quoted values (`POSTHOG_PROJECT_ID="123"` inside a .env file) and stray
 * whitespace reach us verbatim, so strip both before validating.
 */
function normalizeEnvValue(value: string): string {
    const trimmed = value.trim()
    const unquoted = /^(["'])(.*)\1$/s.exec(trimmed)
    return (unquoted?.[2] ?? trimmed).trim()
}

const PROJECT_ID_HELP =
    'Your project id is the number in your PostHog URL (https://us.posthog.com/project/<id>), also shown in Settings → Project.'

/** Never echo a `phc_` key back — the message ends up in error tracking payloads. */
function maskValue(value: string): string {
    return value.startsWith('phc_') ? 'phc_…' : `"${value}"`
}

function rejectionReason(value: string): string | undefined {
    if (/^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?$/.test(value)) {
        return 'the variable was never substituted'
    }
    if (/^YOUR[_-]/i.test(value)) {
        return 'that is a documentation placeholder'
    }
    if (value.startsWith('phc_')) {
        return 'that is a project API key, not a project id'
    }
    return undefined
}

function validateProjectId(entry: EnvEntry | undefined): string | undefined {
    if (!entry) {
        return undefined
    }
    const value = normalizeEnvValue(entry.value)
    if (!value) {
        return undefined
    }

    const reason = rejectionReason(value) ?? (/^\d+$/.test(value) ? undefined : 'project ids are numeric')
    if (reason) {
        throw new Error(`${entry.name} is set to ${maskValue(value)}, but ${reason}. ${PROJECT_ID_HELP}`)
    }
    return value
}

function validateOrganizationId(entry: EnvEntry | undefined): string | undefined {
    if (!entry) {
        return undefined
    }
    const value = normalizeEnvValue(entry.value)
    if (!value) {
        return undefined
    }

    const reason = rejectionReason(value)
    if (reason) {
        throw new Error(
            `${entry.name} is set to ${maskValue(value)}, but ${reason}. Your organization id is the UUID in Settings → Organization.`
        )
    }
    return value
}

function parseVersion(value: string | undefined): number {
    if (!value) {
        return 2
    }
    const parsed = Number(value)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 2
}

export function resolveCliConfig(): CliConfig {
    const apiKey = firstEnv(['POSTHOG_API_KEY', 'POSTHOG_CLI_API_KEY', 'POSTHOG_CLI_TOKEN'])?.trim()
    const organizationId = validateOrganizationId(
        firstEnvEntry(['POSTHOG_ORGANIZATION_ID', 'POSTHOG_CLI_ORGANIZATION_ID'])
    )
    const projectId = validateProjectId(
        firstEnvEntry(['POSTHOG_PROJECT_ID', 'POSTHOG_CLI_PROJECT_ID', 'POSTHOG_CLI_ENV_ID'])
    )

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
