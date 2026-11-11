import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'
import { OrganizationType } from '~/types'

import { workflowSuggestionsAvailabilityLogic } from './workflowSuggestionsAvailabilityLogic'

describe('workflowSuggestionsAvailabilityLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    test.each([
        { approved: true, hasOrg: true, expected: true },
        { approved: false, hasOrg: true, expected: false },
        { approved: null, hasOrg: true, expected: false },
        { approved: undefined, hasOrg: true, expected: false },
        { approved: true, hasOrg: false, expected: false },
    ])('approved $approved, has org $hasOrg -> $expected', ({ approved, hasOrg, expected }) => {
        const organization = {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: approved,
        } as OrganizationType
        organizationLogic.actions.loadCurrentOrganizationSuccess(hasOrg ? organization : null)

        const logic = workflowSuggestionsAvailabilityLogic()
        logic.mount()

        expect(logic.values.suggestionsAvailable).toBe(expected)
    })
})
