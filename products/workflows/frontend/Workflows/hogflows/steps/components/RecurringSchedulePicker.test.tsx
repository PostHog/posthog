import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { workflowLogic } from '../../../workflowLogic'
import { RecurringSchedulePicker } from './RecurringSchedulePicker'

const WORKFLOW_ID = 'wf-schedule-picker'
const STARTS_AT = '2026-04-10T09:00:00.000Z'

describe('RecurringSchedulePicker', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    const renderWithSchedule = (rrule: string): void => {
        act(() => {
            logic.actions.setSchedules([{ id: 'schedule-1', rrule, starts_at: STARTS_AT, timezone: 'UTC' }])
        })
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <RecurringSchedulePicker />
                </BindLogic>
            </Provider>
        )
    }

    it('shows an hourly schedule as hourly', () => {
        renderWithSchedule('FREQ=HOURLY;INTERVAL=1')

        expect(screen.getByText('Hour')).toBeInTheDocument()
        expect(screen.getByText('Runs every hour, starting April 10.')).toBeInTheDocument()
        expect(logic.values.hasUnsavedChanges).toBe(false)
    })

    it('says a rule the controls cannot rebuild stays as it is', () => {
        renderWithSchedule('FREQ=HOURLY;INTERVAL=6;BYHOUR=9,12')

        expect(screen.getByText(/stays as it is/)).toBeInTheDocument()
        expect(screen.getByText('Runs on a custom schedule, starting April 10.')).toBeInTheDocument()
        expect(logic.values.hasUnsavedChanges).toBe(false)
    })
})
