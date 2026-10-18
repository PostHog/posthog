import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { parseWorkflowTriggerPrefill, TRIGGER_PREFILL_PARAM } from '../Workflows/workflowTriggerPrefill'
import { firstWorkflowCardLogic } from './firstWorkflowCardLogic'

describe('firstWorkflowCardLogic', () => {
    let logic: ReturnType<typeof firstWorkflowCardLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['the most-used custom event', [200, { results: [['signed_up']] }], 'signed_up'],
        ['$pageview when the project has no custom events', [200, { results: [] }], '$pageview'],
        ['$pageview when the lookup fails', [500, { detail: 'boom' }], '$pageview'],
    ])('links the shown card to a new workflow triggered by %s', async (_label, queryResponse, expectedEvent) => {
        initKeaTests()
        useMocks({ post: { '/api/environments/:team_id/query/:kind': () => queryResponse } })
        logic = firstWorkflowCardLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.reportShown()).toFinishAllListeners()

        const url = new URL(logic.values.firstWorkflowUrl ?? '', 'http://localhost')
        expect(url.pathname).toBe(urls.workflowNew())
        expect(parseWorkflowTriggerPrefill(url.searchParams.get(TRIGGER_PREFILL_PARAM))).toEqual({
            type: 'event',
            filters: { events: [{ id: expectedEvent, name: expectedEvent, type: 'events' }] },
        })
    })
})
