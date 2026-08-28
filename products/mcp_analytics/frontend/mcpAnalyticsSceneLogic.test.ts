import { type MCPAnalyticsTab, intentClusteringTabVisible } from './mcpAnalyticsSceneLogic'

describe('intentClusteringTabVisible', () => {
    // Without the flag the tab is gone from the nav, but a deep link still has to render it.
    // Filtering it out of the tab list unconditionally leaves anyone holding a link to it on a
    // scene with no content, since the active tab then matches nothing in the list.
    it.each([
        ['hidden without the flag while another tab is open', false, 'dashboard' as MCPAnalyticsTab, false],
        [
            'still rendered without the flag when it is the open tab',
            false,
            'intent-clustering' as MCPAnalyticsTab,
            true,
        ],
        ['shown with the flag while another tab is open', true, 'dashboard' as MCPAnalyticsTab, true],
    ])('is %s', (_label, flagEnabled, activeTab, expected) => {
        expect(intentClusteringTabVisible(flagEnabled, activeTab)).toBe(expected)
    })
})
