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

    it.each([
        [
            'lists what the restore replaced',
            [
                change('draft', 'masked', 'masked'),
                change('restored_version', null, {
                    version: 2,
                    removed_steps: ['Check plan'],
                    added_steps: [],
                    updated_steps: ['Send email'],
                    updated_settings: ['exit_condition'],
                }),
            ],
            [
                'replaced the staged draft of the workflow Welcome email with version 2',
                'Removes steps: Check plan',
                'Changes steps: Send email',
                'Changes: exit condition',
            ],
        ],
        [
            'still reads for entries logged before restores recorded changes',
            [change('draft', 'masked', 'masked')],
            ['replaced the staged draft of the workflow Welcome email with an earlier version'],
        ],
    ])('describes a restored revision: %s', (_label, changes, expected) => {
        const text = getTextContent(
            workflowActivityDescriber({
                ...workflowLogItem(changes as ActivityChange[]),
                activity: 'revision_restored',
            })
        )

        for (const line of expected) {
            expect(text).toContain(line)
        }
    })
})
