import { userHasAccess } from 'lib/utils/accessControlUtils'

import { certificationSuggestionGuards } from './certificationSuggestionGuards'
import type { WarehouseSuggestionApi } from './generated/api.schemas'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    userHasAccess: jest.fn(),
}))

const DEPRECATE_PAYLOAD = { subject_name: 'old_rollup', refresh_seconds_per_month: 60, refresh_bytes_per_month: 0 }

function suggestion(overrides: Partial<WarehouseSuggestionApi>): WarehouseSuggestionApi {
    return {
        id: 's1',
        kind: 'deprecate',
        subject_kind: 'saved_query',
        payload: DEPRECATE_PAYLOAD,
        can_act: true,
        ...overrides,
    } as WarehouseSuggestionApi
}

describe('certificationSuggestionGuards', () => {
    it.each([
        {
            name: 'a catalog viewer cannot accept',
            input: suggestion({}),
            catalogEditor: false,
            inFlight: false,
            expected: {
                acceptBlockedReason: 'You need edit access to the data catalog',
                dismissBlockedReason: undefined,
            },
        },
        {
            name: 'no edit access on the subject blocks every action',
            input: suggestion({ can_act: false }),
            catalogEditor: true,
            inFlight: false,
            expected: {
                acceptBlockedReason: 'You need edit access to this view or table',
                dismissBlockedReason: 'You need edit access to this view or table',
            },
        },
        {
            name: 'an action in flight blocks dismissing only',
            input: suggestion({}),
            catalogEditor: true,
            inFlight: true,
            expected: { acceptBlockedReason: undefined, dismissBlockedReason: 'Working' },
        },
    ])('$name', ({ input, catalogEditor, inFlight, expected }) => {
        jest.mocked(userHasAccess).mockReturnValue(catalogEditor)
        expect(certificationSuggestionGuards(input, false, inFlight)).toMatchObject(expected)
    })

    it.each([
        ['saved_query', true],
        ['table', false],
    ])('a %s deprecation asks for confirmation first: %s', (subjectKind, confirmsFirst) => {
        jest.mocked(userHasAccess).mockReturnValue(true)
        expect(
            certificationSuggestionGuards(
                suggestion({ subject_kind: subjectKind as WarehouseSuggestionApi['subject_kind'] }),
                false,
                false
            ).confirmsFirst
        ).toBe(confirmsFirst)
    })
})
