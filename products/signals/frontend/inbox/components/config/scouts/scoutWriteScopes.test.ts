import { offeredScoutWriteScopes, scoutWriteScopeLabels } from './scoutWriteScopes'

describe('scoutWriteScopes', () => {
    it('labels only the scopes the picker offers', () => {
        // A scope the allowlist dropped is still stored on old configs; labeling it would promise
        // access the token no longer carries.
        expect(scoutWriteScopeLabels(['insight:write', 'dashboard:write', 'cohort:write'])).toEqual([
            'Dashboards',
            'Insights',
        ])
    })

    it('drops a stored scope the picker has no row for', () => {
        // Carrying it into a save would get the whole update rejected, with no switch to clear it.
        expect(offeredScoutWriteScopes(['cohort:write', 'alert:write'])).toEqual(['alert:write'])
    })
})
