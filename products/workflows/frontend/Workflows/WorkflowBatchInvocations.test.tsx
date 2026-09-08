import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ONE_TIME_RRULE } from './hogflows/steps/components/rrule-helpers'
import { HogFlowSchedule } from './hogflows/types'
import { WorkflowBatchInvocations } from './WorkflowBatchInvocations'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-batch-invocations-1'
// Relative to now, so the occurrence stays in the future however long this test lives.
const STARTS_AT = dayjs().add(30, 'day').startOf('hour')

describe('WorkflowBatchInvocations', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    const renderWithSchedule = async (schedule: HogFlowSchedule): Promise<void> => {
        logic.actions.setSchedules([schedule])
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <WorkflowBatchInvocations id={WORKFLOW_ID} />
                </BindLogic>
            </Provider>
        )
        await act(async () => {
            await Promise.resolve()
        })
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/batch_jobs/': [],
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    it('shows the date of a one-time schedule', async () => {
        // A schedule save never stages a draft, so this panel is the only place a person can
        // confirm the date that will run.
        await renderWithSchedule({
            id: 'schedule-1',
            rrule: ONE_TIME_RRULE,
            starts_at: STARTS_AT.toISOString(),
            timezone: 'UTC',
        })

        expect(screen.getByText('Next occurrence')).toBeInTheDocument()
        expect(
            screen.getByText(STARTS_AT.utc().format('dddd, MMMM D YYYY · h:mm A'), { exact: false })
        ).toBeInTheDocument()
    })

    it('shows the recurrence summary of a repeating schedule', async () => {
        await renderWithSchedule({
            id: 'schedule-2',
            rrule: 'FREQ=WEEKLY;INTERVAL=1;BYDAY=MO',
            starts_at: STARTS_AT.toISOString(),
            timezone: 'UTC',
        })

        expect(screen.getByText('Next occurrences')).toBeInTheDocument()
        expect(screen.getByText(/Runs every week on Monday/)).toBeInTheDocument()
    })
})
