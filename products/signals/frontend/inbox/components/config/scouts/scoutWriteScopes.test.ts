import { scoutWriteScopeLabels, toggleScoutWriteScope } from './scoutWriteScopes'

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
                'feature_flag:write',
                'cohort:write',
            ])
        ).toEqual(['Dashboards', 'Insights', 'Skills', 'Replay vision scanners', 'Feature flags'])
    })

    it('preserves unknown scopes when a known grant changes', () => {
        expect(toggleScoutWriteScope(['future:write', 'alert:write'], 'alert:write', false)).toEqual(['future:write'])
        expect(toggleScoutWriteScope(['future:write'], 'alert:write', true)).toEqual(['future:write', 'alert:write'])
        expect(toggleScoutWriteScope(['alert:write'], 'alert:write', true)).toEqual(['alert:write'])
    })
})
