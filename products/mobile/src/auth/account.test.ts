import type { MeApi } from '@/api/users'

import { buildAccount } from './account'

describe('account analytics privacy', () => {
    test.each([true, false, null, undefined])('keeps anonymization safe for preference %s', (preference) => {
        const me: MeApi = {
            id: 1,
            uuid: 'example-user',
            distinct_id: 'example-user',
            email: 'person@example.com',
            first_name: 'Example',
            last_name: 'Person',
            team: null,
            organization: null,
            organizations: [],
            anonymize_data: preference,
        }

        expect(buildAccount(me, []).user.anonymizeData).toBe(preference !== false)
    })
})
