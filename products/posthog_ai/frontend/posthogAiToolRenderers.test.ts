import { toolRegistry } from './components/tool/toolRegistry'

describe('posthogAiToolRenderers', () => {
    it.each([
        ['insight-create', 'Insight'],
        ['insight-update', 'Insight'],
        ['insight-get', 'Insight'],
        ['insight-query', 'Insight query'],
        ['create_insight', 'Insight'],
        ['dashboard-create', 'Dashboard'],
        ['upsert_dashboard', 'Dashboard'],
        ['query-session-recordings-list', 'Session recordings'],
        ['search_session_recordings', 'Session recordings'],
        ['query-error-tracking-issues-list', 'Error tracking'],
        ['search_error_tracking_issues', 'Error tracking'],
        ['query-trends', 'Trends query'],
        ['query-funnel', 'Funnel query'],
        ['notebooks-create', 'Notebook'],
        ['notebook-edit', 'Notebook'],
    ])('resolves %s from the central manifest with displayName "%s"', (key, displayName) => {
        const entry = toolRegistry.lookup(key)
        expect(entry).not.toBeNull()
        expect(entry?.displayName).toEqual(displayName)
    })
})
