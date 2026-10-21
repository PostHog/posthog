import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'
import { OrganizationType } from '~/types'

import { workflowSuggestionsAvailabilityLogic } from './workflowSuggestionsAvailabilityLogic'

describe('workflowSuggestionsAvailabilityLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    test.each([
        { flagOn: true, approved: true, hasOrg: true, expected: true },
        { flagOn: true, approved: false, hasOrg: true, expected: false },
        { flagOn: true, approved: null, hasOrg: true, expected: false },
        { flagOn: true, approved: undefined, hasOrg: true, expected: false },
        { flagOn: true, approved: true, hasOrg: false, expected: false },
        { flagOn: false, approved: true, hasOrg: true, expected: false },
    ])(
        'flag on $flagOn, approved $approved, has org $hasOrg -> $expected',
        ({ flagOn, approved, hasOrg, expected }) => {
            const flags = flagOn ? [FEATURE_FLAGS.SELF_OPTIMISING_WORKFLOWS] : []
            featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
            const organization = {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: approved,
            } as OrganizationType
            organizationLogic.actions.loadCurrentOrganizationSuccess(hasOrg ? organization : null)

            const logic = workflowSuggestionsAvailabilityLogic()
            logic.mount()

            expect(logic.values.suggestionsAvailable).toBe(expected)
        }
    )
})
