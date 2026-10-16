// A tool that is not listed here is never blocked, so a new data-read tool needs an entry here
// or a `query-` name to return the install guidance on a project without events.

import type { FlagValue } from '@/lib/posthog/flags'

export const MCP_NO_DATA_INSTALL_NOTICE_FLAG = 'mcp-no-data-install-notice'
export const NO_DATA_NOTICE_VARIANT = 'test'

export const WIZARD_INSTALL_START_TOOL = 'wizard-install-start'
const GITHUB_CONNECT_URL_TOOL = 'integrations-github-connect-url'

const BLOCKED_TOOL_PREFIX = 'query-'

const BLOCKED_TOOLS: ReadonlySet<string> = new Set([
    'insight-query',
    'dashboard-insights-run',
    'dashboard-widgets-run',
    'persons-list',
    'persons-retrieve',
    'persons-values-retrieve',
    'persons-cohorts-retrieve',
    'session-recording-get',
    'elements-stats-retrieve',
    'heatmaps-list',
    'heatmaps-events',
    'web-analytics-weekly-digest',
    'get-llm-total-costs-for-project',
])

// These tools also read data warehouse tables, so they still answer on a project with warehouse data and no events.
const WAREHOUSE_QUERY_TOOLS: ReadonlySet<string> = new Set(['execute-sql', 'read-data-schema'])

export function isNoDataBlockedTool(toolName: string): boolean {
    return (
        toolName.startsWith(BLOCKED_TOOL_PREFIX) || BLOCKED_TOOLS.has(toolName) || WAREHOUSE_QUERY_TOOLS.has(toolName)
    )
}

export function canQueryWarehouse(toolName: string): boolean {
    return WAREHOUSE_QUERY_TOOLS.has(toolName)
}

export interface NoDataNoticeAudience {
    projectHasData: boolean | undefined
    variant: FlagValue
    isImpersonated?: boolean | undefined
    suppressAnalytics?: boolean | undefined
    apiKeyScopes: readonly string[]
    mcpConsumer: string | undefined
}

// Impersonated sessions, sandbox runs and PostHog AI did not set up the project, so install steps do not help them.
export function isNoDataNoticeActive(audience: NoDataNoticeAudience): boolean {
    return (
        audience.projectHasData === false &&
        audience.variant === NO_DATA_NOTICE_VARIANT &&
        !audience.isImpersonated &&
        !audience.suppressAnalytics &&
        !audience.apiKeyScopes.includes('internal_run:read') &&
        audience.mcpConsumer !== 'posthog_ai'
    )
}

export function buildNoDataInstallNotice({
    projectId,
    offerGitHubInstall,
}: {
    projectId: string
    offerGitHubInstall: boolean
}): string {
    const wizardCommand = `\`npx -y @posthog/wizard@latest --project-id=${projectId}\``
    const intro = `This project (id ${projectId}) hasn't received any events yet, so there is nothing to query.`
    const outro = 'Data appears about a minute after the first event; this message stops then.'
    if (!offerGitHubInstall) {
        return [
            `${intro} Tell the user and offer to install PostHog by running Wizard in their app's folder: ${wizardCommand}. The setup agent installs the SDK and sends the first events.`,
            outro,
        ].join('\n')
    }
    return [
        `${intro} Tell the user and offer two ways to install PostHog:`,
        `1. Run Wizard in their app's folder: ${wizardCommand}. The setup agent installs the SDK and sends the first events.`,
        `2. Connect GitHub with \`${GITHUB_CONNECT_URL_TOOL}\`, then call \`${WIZARD_INSTALL_START_TOOL}\` with the repository, and PostHog opens a pull request that installs it.`,
        outro,
    ].join('\n')
}

export function noDataAnalyticsProperties(
    projectHasData: boolean | undefined,
    variant: FlagValue
): Record<string, unknown> {
    if (projectHasData !== false) {
        return {}
    }
    return {
        mcp_no_data_blocked: false,
        ...(typeof variant === 'string' ? { mcp_no_data_install_notice_variant: variant } : {}),
    }
}
