import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { errorTrackingSceneLogic } from './errorTrackingSceneLogic'

describe('errorTrackingSceneLogic', () => {
    it('restores the active tab from the canonical error-tracking url', () => {
        initKeaTests()
        const logic = errorTrackingSceneLogic()
        logic.mount()

        router.actions.push('/error-tracking', { activeTab: 'configuration' })

        expect(logic.values.activeTab).toBe('configuration')
    })
})
