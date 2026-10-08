import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, within } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

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

const echoSave = async ({ request }: { request: Request }): Promise<[number, Experiment]> => [
    200,
    { ...savedExperiment, ...(await request.json()) },
]

const RESPONSES = {
    fails: () => [400, { type: 'validation_error', code: 'invalid_input', detail: VALIDATION_DETAIL, attr: null }],
    conflicts: () => [409, { type: 'validation_error', code: 'conflict', detail: CONFLICT_DETAIL, current_version: 2 }],
    succeeds: echoSave,
}

describe('ExperimentDateRange', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    function pickDay(boundary: 'start' | 'end'): HTMLElement {
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
        return trigger
    }

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
            const trigger = pickDay(boundary)

            fireEvent.click(getByDataAttr(document.body, 'lemon-calendar-select-apply'))
            await act(() => expectLogic(logic).toFinishAllListeners())

            expect(trigger).toHaveTextContent(SHOWN_DATES[boundary][shown])
            expect(trigger.classList.contains('LemonButton--active')).toBe(open)
            expect(jest.mocked(lemonToast.error).mock.calls).toEqual(
                toasts.map((text) => [expect.stringContaining(text)])
            )
        }
    )

    it('applies a date once and stays open while the save runs', async () => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        let finishSave = (): void => {}
        const saveFinished = new Promise<void>((resolve) => {
            finishSave = resolve
        })
        useMocks({
            patch: {
                '/api/projects/:team/experiments/:id': async (request: { request: Request }) => {
                    await saveFinished
                    return echoSave(request)
                },
            },
        })
        const trigger = pickDay('start')

        fireEvent.click(getByDataAttr(document.body, 'lemon-calendar-select-apply'))
        fireEvent.click(getByDataAttr(document.body, 'lemon-calendar-select-apply'))
        fireEvent.click(getByDataAttr(document.body, 'lemon-calendar-select-cancel'))

        expect(getByDataAttr(document.body, 'lemon-calendar-select-apply')).toHaveClass('LemonButton--loading')
        expect(trigger).toHaveClass('LemonButton--active')

        finishSave()
        await act(() => expectLogic(logic).toFinishAllListeners())

        expect(trigger).not.toHaveClass('LemonButton--active')
        expect(captureSpy.mock.calls.filter(([event]) => event === 'experiment start date changed')).toHaveLength(1)
    })
})
