import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { emailBrandEntryLogic } from './emailBrandEntryLogic'
import { exampleBrand } from './fixtures'

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
    it.each(['saved', 'missing'])('keeps the completed brand when an older summary reports %s', async (outcome) => {
        let finish: () => void = () => {}
        const waiting = new Promise<void>((resolve) => {
            finish = resolve
        })
        useMocks({
            get: {
                '/api/projects/:id/email_brand/current/': async () => {
                    await waiting
                    return outcome === 'missing'
                        ? [404, { detail: 'Not found' }]
                        : { ...exampleBrand, name: 'Old brand' }
                },
            },
        })
        featureFlagLogic.actions.setFeatureFlags(['workflows-brand-detection'], { 'workflows-brand-detection': true })
        const logic = emailBrandEntryLogic({ entryPoint: 'channels' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadEmailBrandSummary'])
        logic.actions.complete({ ...exampleBrand, name: 'Saved new brand' }, null)
        finish()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.summary?.name).toBe('Saved new brand')
        logic.unmount()
    })
    it('loads the saved summary once when the feature becomes enabled after mount', async () => {
        const read = jest.fn(() => exampleBrand)
        useMocks({ get: { '/api/projects/:id/email_brand/current/': read } })
        featureFlagLogic.actions.setFeatureFlags([], { 'workflows-brand-detection': false })
        const logic = emailBrandEntryLogic({ entryPoint: 'channels' })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(read).not.toHaveBeenCalled()
        await expectLogic(logic, () =>
            featureFlagLogic.actions.setFeatureFlags(['workflows-brand-detection'], {
                'workflows-brand-detection': true,
            })
        ).toFinishAllListeners()
        await expectLogic(logic, () =>
            featureFlagLogic.actions.setFeatureFlags(['workflows-brand-detection'], {
                'workflows-brand-detection': true,
            })
        ).toFinishAllListeners()
        expect(read).toHaveBeenCalledTimes(1)
        expect(logic.values.summary?.name).toBe('Juniper')
        logic.unmount()
    })
})
