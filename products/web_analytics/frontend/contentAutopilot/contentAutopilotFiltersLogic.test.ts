import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({ lemonToast: { error: jest.fn() } }))

describe('contentAutopilotFiltersLogic', () => {
    let logic: ReturnType<typeof contentAutopilotFiltersLogic.build>

    beforeEach(() => {
        // The branded segment persists in local storage, so a choice made in one test must not leak into the next.
        localStorage.clear()
        jest.mocked(lemonToast.error).mockClear()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        [
            'every filter',
            '/web/content-autopilot?date_from=2026-10-01&date_to=2026-10-07&engine=claude-web-search&topic=Pricing&branded=all',
            {
                dateFrom: '2026-10-01',
                dateTo: '2026-10-07',
                engine: 'claude-web-search',
                topic: 'Pricing',
                branded: 'all',
            },
        ],
        [
            'an empty topic',
            '/web/content-autopilot?topic=',
            { dateFrom: '-30d', dateTo: null, engine: null, topic: '', branded: 'non_branded' },
        ],
        [
            'values it does not know',
            '/web/content-autopilot?date_from=-24h&days=soon&branded=maybe',
            { dateFrom: '-30d', dateTo: null, engine: null, topic: null, branded: 'non_branded' },
        ],
        [
            'the days of a link from before the date range',
            '/web/content-autopilot?days=7',
            { dateFrom: '-7d', dateTo: null, engine: null, topic: null, branded: 'non_branded' },
        ],
        [
            'a prompt page',
            '/web/content-autopilot/prompts/abc?date_from=-90d&engine=exa-answer',
            { dateFrom: '-90d', dateTo: null, engine: 'exa-answer', topic: null, branded: 'non_branded' },
        ],
    ])('reads %s from the URL', async (_, url, expected) => {
        router.actions.push(url)
        logic = contentAutopilotFiltersLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ filters: expected })
    })

    it('writes the filters to the URL and keeps the other params', async () => {
        router.actions.push('/web/content-autopilot', { other: 'kept', days: 7 })
        logic = contentAutopilotFiltersLogic()
        logic.mount()

        logic.actions.setDates('2026-10-01', '2026-10-07', 'overview')
        logic.actions.setEngine('exa-answer', 'overview')
        logic.actions.setTopic('', 'overview')
        logic.actions.setBrandedSegment('branded', 'overview')
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname).toMatch(/\/web\/content-autopilot$/)
        expect(router.values.searchParams).toEqual({
            other: 'kept',
            date_from: '2026-10-01',
            date_to: '2026-10-07',
            engine: 'exa-answer',
            topic: '',
            branded: 'branded',
        })

        logic.actions.setDates('-30d', null, 'overview')
        logic.actions.setEngine(null, 'overview')
        logic.actions.setTopic(null, 'overview')
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.searchParams).toEqual({ other: 'kept', branded: 'branded' })
    })

    it.each([
        ['longer than the API serves', '-180d', null],
        ['longer than the API serves, as two dates', '2026-01-01', '2026-06-01'],
        ['in hours', '-24h', null],
    ])('keeps the current range and says why when the picked one is %s', async (_, dateFrom, dateTo) => {
        router.actions.push('/web/content-autopilot')
        logic = contentAutopilotFiltersLogic()
        logic.mount()

        logic.actions.pickDates(dateFrom, dateTo, 'overview')
        await expectLogic(logic)
            .toFinishAllListeners()
            .toNotHaveDispatchedActions(['setDates'])
            .toMatchValues({ dateFrom: '-30d', dateTo: null })
        expect(lemonToast.error).toHaveBeenCalledTimes(1)

        logic.actions.pickDates('-90d', null, 'overview')
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ dateFrom: '-90d', dateTo: null })
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
