import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { emailBrandEntryLogic } from './emailBrandEntryLogic'

describe('emailBrandEntryLogic', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/projects/:id/email_brand/current/': () => [404, { detail: 'Not found.' }] } })
        initKeaTests()
    })

    it.each(['channels', 'template_library'] as const)(
        'hides the %s entry and refuses to open with the flag off',
        async (entryPoint) => {
            const logic = emailBrandEntryLogic({ entryPoint })
            await expectLogic(logic, () => {
                logic.mount()
            }).toFinishAllListeners()
            featureFlagLogic.actions.setFeatureFlags([], { 'workflows-brand-detection': false })
            logic.actions.openFlow()
            expect(logic.values.enabled).toBe(false)
            expect(logic.values.isOpen).toBe(false)
            featureFlagLogic.actions.setFeatureFlags(['workflows-brand-detection'], {
                'workflows-brand-detection': true,
            })
            logic.actions.openFlow()
            expect(logic.values.enabled).toBe(true)
            expect(logic.values.isOpen).toBe(true)
            logic.unmount()
        }
    )
})
