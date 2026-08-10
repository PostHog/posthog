import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { batchSpikeEventsLogic } from './batchSpikeEventsLogic'

describe('batchSpikeEventsLogic', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.ErrorTracking]: AccessControlLevel.None,
            },
        } as AppContext
        initKeaTests()
    })

    it('does not request spike events without error tracking viewer access', async () => {
        const getSpikeEvents = jest.spyOn(api.errorTracking, 'getSpikeEvents')
        const logic = batchSpikeEventsLogic()
        logic.mount()

        logic.actions.loadSpikeEventsForIssues(['issue-id'])
        await expectLogic(logic).toDispatchActions(['loadSpikeEventsForIssuesSuccess'])

        expect(getSpikeEvents).not.toHaveBeenCalled()
        expect(logic.values.rawSpikeEvents).toEqual([])

        logic.unmount()
    })
})
