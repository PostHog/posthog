import { FEATURE_FLAGS } from 'lib/constants'

import { filterVisibleScoutWriteScopeRows, offeredScoutWriteScopes, scoutWriteScopeLabels } from './scoutWriteScopes'

describe('scoutWriteScopes', () => {
    it('labels only the scopes the picker offers', () => {
        // A scope the allowlist dropped is still stored on old configs; labeling it would promise
        // access the token no longer carries.
        expect(
            scoutWriteScopeLabels([
                'insight:write',
                'llm_skill:write',
                'dashboard:write',
                'replay_scanner:write',
                'customer_task:write',
                'cohort:write',
            ])
        ).toEqual(['Dashboards', 'Insights', 'Customer tasks', 'Skills', 'Replay vision scanners'])
    })

    it('drops a stored scope the picker has no row for', () => {
        // Carrying it into a save would get the whole update rejected, with no switch to clear it.
        expect(offeredScoutWriteScopes(['cohort:write', 'alert:write'])).toEqual(['alert:write'])
    })

    it.each([
        [{}, false],
        [{ [FEATURE_FLAGS.CUSTOMER_ANALYTICS_CUSTOMER_TASKS]: true }, true],
    ])('shows the customer tasks row only behind its flag (flags %o)', (featureFlags, shown) => {
        const scopes = filterVisibleScoutWriteScopeRows(featureFlags).map((row) => row.scope)
        expect(scopes.includes('customer_task:write')).toBe(shown)
        expect(scopes).toContain('dashboard:write')
    })
})
