// Pure helpers for splitting a snapshot identifier into theme + area buckets.
// Used by the snapshots-overview scene for client-side facet derivation. Stays
// in sync with `_derive_area` if/when the backend ever needs to mirror it for
// a server-side facet.

// Map of known PostHog area keywords (matched as `-`-separated tokens, not
// substrings, to avoid `errortracking` matching `tracking`). Order doesn't
// matter — first hit wins, but the keys are disjoint enough that there's no
// real ambiguity.
const AREA_TOKENS: Array<[string[], string]> = [
    [['insight', 'insights'], 'Insights'],
    [['dashboard', 'dashboards'], 'Dashboards'],
    [['replay', 'recording', 'recordings', 'session-replay'], 'Session replay'],
    [['funnel', 'funnels'], 'Funnels'],
    [['retention'], 'Retention'],
    [['feature-flag', 'feature-flags', 'flags'], 'Feature flags'],
    [['experiment', 'experiments'], 'Experiments'],
    [['survey', 'surveys'], 'Surveys'],
    [['notebook', 'notebooks'], 'Notebooks'],
    [['person', 'persons', 'cohort', 'cohorts'], 'Persons'],
    [['data-management', 'datamanagement'], 'Data management'],
    [['data-warehouse', 'datawarehouse', 'data-pipelines', 'datapipelines', 'batchexports'], 'Data pipelines'],
    [['onboarding'], 'Onboarding'],
    [['setting', 'settings'], 'Settings'],
    [['error-tracking', 'errortracking'], 'Error tracking'],
    [['web-analytics', 'webanalytics'], 'Web analytics'],
    [['llm-analytics', 'llmanalytics'], 'LLM analytics'],
    [['toolbar'], 'Toolbar'],
    [['heatmap', 'heatmaps'], 'Heatmaps'],
    [['workflow', 'workflows'], 'Workflows'],
    [['visual-review', 'visual_review'], 'Visual review'],
    [['customer-analytics', 'customeranalytics'], 'Customer analytics'],
    [['revenue-analytics', 'revenueanalytics'], 'Revenue analytics'],
    [['marketing-analytics', 'marketinganalytics'], 'Marketing analytics'],
    [['inbox'], 'Inbox'],
    [['activity'], 'Activity'],
    [['annotations'], 'Annotations'],
    [['apps', 'plugins'], 'Apps'],
    [['comments'], 'Comments'],
    [['integrations'], 'Integrations'],
    [['exports', 'exporter'], 'Exports'],
    [['actions'], 'Actions'],
    [['endpoints'], 'Endpoints'],
    [['mcp'], 'MCP'],
    [['posthog-3000', 'theme'], 'Theming'],
    [['lemon', 'ui'], 'UI primitives'],
]

export type Theme = 'light' | 'dark' | null

export function parseTheme(identifier: string): { stem: string; theme: Theme } {
    if (identifier.endsWith('--light')) {
        return { stem: identifier.slice(0, -'--light'.length), theme: 'light' }
    }
    if (identifier.endsWith('--dark')) {
        return { stem: identifier.slice(0, -'--dark'.length), theme: 'dark' }
    }
    return { stem: identifier, theme: null }
}

export function parseArea(identifier: string): string {
    // Identifier shape varies — sometimes `<area>--<name>`, often something
    // like `scenes-app-<area>-...` for Storybook stories, or `components-...`
    // for component-level shots. Walk the first few `-`-separated tokens and
    // return the first one we recognize.
    const stem = parseTheme(identifier).stem
    const head = stem.split('--')[0].toLowerCase()
    const tokens = head.split('-')

    // Storybook story IDs nest the area inside `scenes-app-<area>-...`. Skip
    // the wrapper segments to look for the real area first.
    const startIndex = tokens[0] === 'scenes' && tokens[1] === 'app' ? 2 : 0

    // Try multi-token matches (e.g. "data-management") first, then single tokens.
    for (let i = startIndex; i < tokens.length; i++) {
        for (let span = Math.min(3, tokens.length - i); span >= 1; span--) {
            const candidate = tokens.slice(i, i + span).join('-')
            for (const [keys, label] of AREA_TOKENS) {
                if (keys.includes(candidate)) {
                    return label
                }
            }
        }
    }

    if (tokens[0] === 'components') {
        return 'Components'
    }
    return 'Other'
}

// Display-friendly run-type label ("playwright · chromium" for Playwright runs
// where we know the browser; otherwise just the run_type itself).
export function runTypeLabel(runType: string, browser: string | null | undefined): string {
    if (runType.toLowerCase() === 'playwright' && browser) {
        return `playwright · ${browser}`
    }
    return runType
}
