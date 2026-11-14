import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'

describe('contentAutopilotFiltersLogic', () => {
    let logic: ReturnType<typeof contentAutopilotFiltersLogic.build>

    beforeEach(() => {
        // The branded segment persists in local storage, so a choice made in one test must not leak into the next.
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        [
            'every filter',
            '/web/content-autopilot?days=7&engine=claude-web-search&topic=Pricing&branded=all',
            { days: 7, engine: 'claude-web-search', topic: 'Pricing', branded: 'all' },
        ],
        [
            'an empty topic',
            '/web/content-autopilot?topic=',
            { days: 30, engine: null, topic: '', branded: 'non_branded' },
        ],
        [
            'values it does not know',
            '/web/content-autopilot?days=3&branded=maybe',
            { days: 30, engine: null, topic: null, branded: 'non_branded' },
        ],
        [
            'a prompt page',
            '/web/content-autopilot/prompts/abc?days=90&engine=exa-answer',
            { days: 90, engine: 'exa-answer', topic: null, branded: 'non_branded' },
        ],
    ])('reads %s from the URL', async (_, url, expected) => {
        router.actions.push(url)
        logic = contentAutopilotFiltersLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ filters: expected })
    })

    it('writes the filters to the URL and keeps the other params', async () => {
        router.actions.push('/web/content-autopilot', { other: 'kept' })
        logic = contentAutopilotFiltersLogic()
        logic.mount()

        logic.actions.setDays(14, 'overview')
        logic.actions.setEngine('exa-answer', 'overview')
        logic.actions.setTopic('', 'overview')
        logic.actions.setBrandedSegment('branded', 'overview')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toMatch(/\/web\/content-autopilot$/)
        expect(router.values.searchParams).toEqual({
            other: 'kept',
            days: 14,
            engine: 'exa-answer',
            topic: '',
            branded: 'branded',
        })

        logic.actions.setDays(30, 'overview')
        logic.actions.setEngine(null, 'overview')
        logic.actions.setTopic(null, 'overview')
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.searchParams).toEqual({ other: 'kept', branded: 'branded' })
    })

    it('leaves URLs outside AI visibility alone', async () => {
        router.actions.push('/web')
        logic = contentAutopilotFiltersLogic()
        logic.mount()

        logic.actions.setEngine('exa-answer', 'overview')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toMatch(/\/web$/)
        expect(router.values.searchParams).toEqual({})
    })
})
