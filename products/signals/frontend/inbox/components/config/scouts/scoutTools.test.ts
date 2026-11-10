import { SCOUT_TOOL_CATALOGUE } from './scoutToolFixtures'
import { deriveScoutToolWriteScopes, groupScoutTools } from './scoutTools'

describe('scoutTools', () => {
    it.each([
        ['read tools only', ['dashboard-get', 'insight-get'], []],
        // `query:read` rides along on a write tool but is not a grant, so it must not show as write access.
        ['a write tool with a read scope too', ['insight-create'], ['insight:write']],
        // `ticket:write` is not grantable, so the API drops it from the derived scopes.
        ['a write tool outside the grantable set', ['conversations-tickets-notes-create'], []],
        ['two write tools', ['insight-create', 'dashboard-update'], ['dashboard:write', 'insight:write']],
    ])('derives the write access the API saves, for %s', (_name, selected, expected) => {
        expect(deriveScoutToolWriteScopes(SCOUT_TOOL_CATALOGUE, selected)).toEqual(expected)
    })

    it.each([
        ['', ['Dashboards', 'Feature flags', 'Product analytics', 'Support']],
        ['insight', ['Product analytics']],
        ['DASHBOARD', ['Dashboards']],
        // The run context tools are always held, so a search never offers them as choices.
        ['scout', []],
        ['skill', []],
    ])('groups the selectable tools for search %p', (search, categories) => {
        expect(groupScoutTools(SCOUT_TOOL_CATALOGUE, search).map((group) => group.category)).toEqual(categories)
    })
})
