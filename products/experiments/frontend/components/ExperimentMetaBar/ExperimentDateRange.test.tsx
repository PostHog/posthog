import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, within } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import { useMocks } from '~/mocks/jest'
import { getByDataAttr } from '~/test/byDataAttr'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { NEW_EXPERIMENT } from 'products/experiments/frontend/constants'

import { ExperimentDateRange } from './ExperimentDateRange'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn() },
}))

const EXPERIMENT_ID = 7
const VALIDATION_DETAIL = 'End date must be after start date'
const CONFLICT_DETAIL = 'This experiment was changed by someone else.'

const savedExperiment = {
    ...NEW_EXPERIMENT,
    id: EXPERIMENT_ID,
    version: 1,
    start_date: '2026-01-05T10:00:00Z',
    end_date: '2026-02-05T10:00:00Z',
} as Experiment
const serverExperiment = {
    ...savedExperiment,
    version: 2,
    start_date: '2026-01-03T10:00:00Z',
    end_date: '2026-02-20T10:00:00Z',
} as Experiment

const SHOWN_DATES = {
    start: { saved: 'Jan 5, 2026', picked: 'Jan 12, 2026', server: 'Jan 3, 2026' },
    end: { saved: 'Feb 5, 2026', picked: 'Feb 12, 2026', server: 'Feb 20, 2026' },
}

const RESPONSES = {
    fails: () => [400, { type: 'validation_error', code: 'invalid_input', detail: VALIDATION_DETAIL, attr: null }],
    conflicts: () => [409, { type: 'validation_error', code: 'conflict', detail: CONFLICT_DETAIL, current_version: 2 }],
    succeeds: async ({ request }: { request: Request }) => [200, { ...savedExperiment, ...(await request.json()) }],
}

describe('ExperimentDateRange', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it.each([
        { boundary: 'start', outcome: 'fails', open: true, shown: 'saved', toasts: [VALIDATION_DETAIL] },
        { boundary: 'end', outcome: 'fails', open: true, shown: 'saved', toasts: [VALIDATION_DETAIL] },
        { boundary: 'start', outcome: 'conflicts', open: true, shown: 'server', toasts: [CONFLICT_DETAIL] },
        { boundary: 'end', outcome: 'conflicts', open: true, shown: 'server', toasts: [CONFLICT_DETAIL] },
        { boundary: 'start', outcome: 'succeeds', open: false, shown: 'picked', toasts: [] },
        { boundary: 'end', outcome: 'succeeds', open: false, shown: 'picked', toasts: [] },
    ] as const)(
        'when the save $outcome, the $boundary date picker is open: $open, and the page shows the $shown date',
        async ({ boundary, outcome, open, shown, toasts }) => {
            useMocks({
                get: { '/api/projects/:team/experiments/:id': serverExperiment },
                patch: { '/api/projects/:team/experiments/:id': RESPONSES[outcome] },
            })
            initKeaTests()
            logic = experimentLogic({ experimentId: EXPERIMENT_ID })
            logic.mount()
            logic.actions.setUnmodifiedExperiment(savedExperiment)
            logic.actions.setExperiment(savedExperiment)

            const { container } = render(
                <Provider>
                    <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
                        <ExperimentDateRange />
                    </BindLogic>
                </Provider>
            )
            const trigger = getByDataAttr(container, `experiment-${boundary}-date`)

            fireEvent.click(trigger)
            expect(trigger).toHaveClass('LemonButton--active')
            const month = document.querySelector('.LemonCalendar__month') as HTMLElement
            fireEvent.click(within(month).getByText('12'))
            fireEvent.click(getByDataAttr(document.body, 'lemon-calendar-select-apply'))
            await act(async () => {
                await expectLogic(logic).toFinishAllListeners()
                // The picker acts on the save outcome after the listeners settle, so drain the microtask queue. waitFor
                // cannot replace this, because an open picker looks the same before and after the outcome.
                await new Promise((resolve) => setTimeout(resolve, 0))
            })

            expect(trigger).toHaveTextContent(SHOWN_DATES[boundary][shown])
            expect(trigger.classList.contains('LemonButton--active')).toBe(open)
            expect(jest.mocked(lemonToast.error).mock.calls).toEqual(
                toasts.map((text) => [expect.stringContaining(text)])
            )
        }
    )
})
