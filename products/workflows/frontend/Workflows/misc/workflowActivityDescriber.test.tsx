import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { workflowActivityDescriber } from './workflowActivityDescriber'

const getTextContent = (describer: { description: JSX.Element | string | null }): string => {
    if (!describer.description || typeof describer.description === 'string') {
        return (describer.description as string) || ''
    }
    const { container } = render(describer.description)
    return container.textContent || ''
}

const workflowLogItem = (changes: ActivityChange[]): ActivityLogItem => ({
    activity: 'updated',
    created_at: '2026-07-29T10:00:00Z',
    scope: 'HogFlow',
    item_id: 'flow-uuid',
    detail: { merge: null, trigger: null, changes, name: 'Welcome email' },
})

const change = (field: string, before: unknown, after: unknown): ActivityChange =>
    ({ type: ActivityScope.HOG_FLOW, action: 'changed', field, before, after }) as ActivityChange

describe('workflowActivityDescriber', () => {
    // The backend masks `actions` because the graph can carry secret function inputs, so the log
    // holds the string 'masked'. Mapping over that threw "itemsAfter.map is not a function" and
    // took the whole History tab down with an error boundary.
    it.each([
        ['masked string', 'masked'],
        ['object', {}],
        ['number', 7],
    ])('renders a plain line when an actions value is not an array (%s)', (_label, after) => {
        const text = getTextContent(workflowActivityDescriber(workflowLogItem([change('actions', null, after)])))

        expect(text).toContain('updated actions')
    })

    const ONE_TIME_OCT_20 = {
        rrule: 'FREQ=DAILY;COUNT=1',
        starts_at: '2026-10-20T10:00:00+00:00',
        timezone: 'Europe/London',
    }
    const ONE_TIME_OCT_22 = { ...ONE_TIME_OCT_20, starts_at: '2026-10-22T10:00:00+00:00' }
    const WEEKLY = { rrule: 'FREQ=WEEKLY;BYDAY=TU', starts_at: '2026-09-01T09:00:00+00:00', timezone: 'UTC' }

    it.each([
        [
            'moved',
            'changed',
            ONE_TIME_OCT_20,
            ONE_TIME_OCT_22,
            'moved a schedule from Oct 20, 2026 at 11:00 AM (Europe/London) to Oct 22, 2026 at 11:00 AM (Europe/London)',
        ],
        ['added', 'created', null, WEEKLY, 'added a schedule: every week on Tuesday at 9:00 AM (UTC)'],
        ['removed', 'deleted', WEEKLY, null, 'removed a schedule: every week on Tuesday at 9:00 AM (UTC)'],
    ])('describes a schedule that was %s', (_label, action, before, after, expected) => {
        const scheduleChange = {
            type: ActivityScope.HOG_FLOW,
            action,
            field: 'schedule',
            before,
            after,
        } as ActivityChange
        const text = getTextContent(workflowActivityDescriber(workflowLogItem([scheduleChange])))

        expect(text).toContain(expected)
    })

    it('still diffs individual items when both sides really are arrays', () => {
        const text = getTextContent(
            workflowActivityDescriber(
                workflowLogItem([
                    change('actions', [{ id: 'a1', name: 'Send email' }], [{ id: 'a2', name: 'Send push' }]),
                ])
            )
        )

        expect(text).toContain('added action Send push')
        expect(text).toContain('deleted action Send email')
    })
})
