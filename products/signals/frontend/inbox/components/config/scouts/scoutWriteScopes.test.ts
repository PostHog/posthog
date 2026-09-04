import type { UserBasicType } from '~/types'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutWriteAccessDisabledReason, scoutWriteScopeLabels } from './scoutWriteScopes'

const OWNER = { uuid: 'ada-uuid', first_name: 'Ada', email: 'ada@example.com' } as UserBasicType

function config(owners: UserBasicType[]): SignalScoutConfigApi {
    return { owners } as SignalScoutConfigApi
}

describe('scoutWriteScopes', () => {
    it.each([
        ['a project admin', [OWNER], true, 'someone-else', true],
        ['an owner of the scout', [OWNER], false, 'ada-uuid', true],
        // Nobody owns the scout, so the API falls back to whoever authored it. That can't be
        // answered here, so the switches stay live and the API gets to refuse the write.
        ['anyone, when the scout has no owners', [], false, 'someone-else', true],
        ['a member who is neither', [OWNER], false, 'someone-else', false],
    ])('lets %s edit write access: %s', (_who, owners, isProjectAdmin, currentUserUuid, allowed) => {
        const reason = scoutWriteAccessDisabledReason(config(owners as UserBasicType[]), {
            isProjectAdmin: isProjectAdmin as boolean,
            currentUserUuid: currentUserUuid as string,
        })

        expect(reason === undefined).toBe(allowed)
        if (!allowed) {
            // The refusal names who to ask, so a member who can't edit knows the next step.
            expect(reason).toContain('Ada')
        }
    })

    it('labels only the scopes the picker offers', () => {
        // A scope the allowlist dropped is still stored on old configs; labeling it would promise
        // access the token no longer carries.
        expect(scoutWriteScopeLabels(['insight:write', 'dashboard:write', 'cohort:write'])).toEqual([
            'Dashboards',
            'Insights',
        ])
    })
})
