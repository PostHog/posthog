import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { parseWorkflowTriggerPrefill, TRIGGER_PREFILL_PARAM } from '../Workflows/workflowTriggerPrefill'
import { firstWorkflowCardLogic } from './firstWorkflowCardLogic'

describe('firstWorkflowCardLogic', () => {
    let logic: ReturnType<typeof firstWorkflowCardLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    // The card promises a workflow built on the project's own events, so the click has to land on
    // one, and has to land somewhere even when the lookup finds nothing or fails.
    it.each([
        ['the most-used custom event', [200, { results: [['signed_up']] }], 'signed_up'],
        ['$pageview when the project has no custom events', [200, { results: [] }], '$pageview'],
        ['$pageview when the lookup fails', [500, { detail: 'boom' }], '$pageview'],
    ])('opens a new workflow triggered by %s', async (_label, queryResponse, expectedEvent) => {
        initKeaTests()
        useMocks({ post: { '/api/environments/:team_id/query/:kind': () => queryResponse } })
        logic = firstWorkflowCardLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.openFirstWorkflow()).toFinishAllListeners()

        expect(router.values.location.pathname).toMatch(/\/workflows\/new/)
        expect(parseWorkflowTriggerPrefill(router.values.searchParams[TRIGGER_PREFILL_PARAM])).toEqual({
            type: 'event',
            filters: { events: [{ id: expectedEvent, name: expectedEvent, type: 'events' }] },
        })
    })
})
