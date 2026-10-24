// pinned: analytics event names. Renaming one breaks the dashboards built on it.
export const CUSTOM_CHART_EVENTS = {
    created: 'custom chart created',
    built: 'custom chart built',
    buildFailed: 'custom chart build failed',
    refined: 'custom chart refined',
    removed: 'custom chart removed',
    rendered: 'custom chart rendered',
    runtimeError: 'custom chart runtime error',
} as const
