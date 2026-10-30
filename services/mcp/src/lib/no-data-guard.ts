import type { FlagValue } from '@/lib/posthog/flags'

export const MCP_NO_DATA_INSTALL_NOTICE_FLAG = 'mcp-no-data-install-notice'
export type NoDataNoticeMode = 'warn' | 'block'
export type NoDataAction = 'warned' | 'blocked'

export class NoDataInstallNoticeError extends Error {
    constructor(
        public readonly toolName: string,
        public readonly text: string
    ) {
        super(text)
        this.name = 'NoDataInstallNoticeError'
    }
}

export function noDataNoticeMode(variant: FlagValue): NoDataNoticeMode | undefined {
    return variant === 'warn' || variant === 'block' ? variant : undefined
}

export const INGESTED_DATA_KINDS = ['events', 'events_or_warehouse'] as const
export type IngestedDataKind = (typeof INGESTED_DATA_KINDS)[number]

export const WIZARD_INSTALL_START_TOOL = 'wizard-install-start'

export interface NoDataNoticeAudience {
    projectHasData: boolean | undefined
    variant: FlagValue
    isImpersonated?: boolean | undefined
    suppressAnalytics?: boolean | undefined
    apiKeyScopes: readonly string[]
    mcpConsumer: string | undefined
}

// Impersonated sessions, sandbox runs and PostHog AI did not set up the project, so install steps do not help them.
export function resolveNoDataNoticeMode(audience: NoDataNoticeAudience): NoDataNoticeMode | undefined {
    if (
        audience.projectHasData !== false ||
        audience.isImpersonated ||
        audience.suppressAnalytics ||
        audience.apiKeyScopes.includes('internal_run:read') ||
        audience.mcpConsumer === 'posthog_ai'
    ) {
        return undefined
    }
    return noDataNoticeMode(audience.variant)
}

export function githubConnectUrl(publicBaseUrl: string, projectId: string): string {
    const params = new URLSearchParams({ project_id: projectId, connect_from: 'mcp' })
    return `${publicBaseUrl.replace(/\/+$/, '')}/integrations/connect/github/?${params.toString()}`
}

export function buildNoDataInstallNotice({
    projectId,
    githubConnectUrl,
}: {
    projectId: string
    /** Set only when the GitHub pull request route is available. */
    githubConnectUrl?: string | undefined
}): string {
    const wizardCommand = `\`npx -y @posthog/wizard@latest --project-id=${projectId}\``
    const intro = `This project (id ${projectId}) hasn't received any events yet, so there is nothing to query.`
    const wizardOption = `If you can run commands in the user's codebase, run Wizard in their app's folder: ${wizardCommand}. The setup agent installs the SDK and sends the first events.`
    const outro = 'Data appears about a minute after the first event; this message stops then.'
    if (!githubConnectUrl) {
        return [`${intro} Tell the user and offer to install PostHog.`, wizardOption, outro].join('\n')
    }
    return [
        `${intro} Tell the user and offer to install PostHog:`,
        `1. ${wizardOption}`,
        `2. Otherwise, call \`${WIZARD_INSTALL_START_TOOL}\` with the repository, and PostHog opens a pull request that installs it. If the project isn't connected to GitHub yet, give the user this link first: ${githubConnectUrl}`,
        outro,
    ].join('\n')
}

// A separate content block keeps the tool's own text intact, so a `--json` result still parses.
export function prependNoDataNotice(result: unknown, notice: string): unknown {
    if (
        typeof result !== 'object' ||
        result === null ||
        (result as { isError?: unknown }).isError === true ||
        !Array.isArray((result as { content?: unknown }).content)
    ) {
        return result
    }
    const withContent = result as { content: unknown[] }
    return { ...withContent, content: [{ type: 'text', text: notice }, ...withContent.content] }
}

export function noDataAnalyticsProperties(
    projectHasData: boolean | undefined,
    variant: FlagValue,
    action: NoDataAction | undefined
): Record<string, unknown> {
    if (projectHasData !== false) {
        return {}
    }
    return {
        mcp_no_data_action: action ?? 'none',
        // The experiment uses this tool call as its custom exposure event, and a custom exposure event
        // assigns the variant only through `$feature/<flag key>`. The server reads flags without an exposure event.
        ...(typeof variant === 'string' ? { [`$feature/${MCP_NO_DATA_INSTALL_NOTICE_FLAG}`]: variant } : {}),
    }
}
