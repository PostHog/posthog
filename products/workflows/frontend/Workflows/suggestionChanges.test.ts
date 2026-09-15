import type { HogFlow } from './hogflows/types'
import { describeSuggestedChanges } from './suggestionChanges'

const live = {
    name: 'Onboarding welcome',
    actions: [
        {
            id: 'email_1',
            name: 'Welcome email',
            config: { inputs: { email: { value: { subject: 'Old subject', html: '<p>hi</p>' } } } },
        },
    ],
} as unknown as HogFlow

describe('describeSuggestedChanges', () => {
    it('pairs each changed field with the live value at the same path and names the step', () => {
        const changes = describeSuggestedChanges(
            {
                actions: [
                    { id: 'email_1', config: { inputs: { email: { value: { subject: 'New subject', html: null } } } } },
                ],
            },
            live
        )

        expect(changes.workflow).toEqual([])
        expect(changes.steps).toEqual([
            {
                stepId: 'email_1',
                stepName: 'Welcome email',
                fields: [
                    {
                        path: 'config.inputs.email.value.subject',
                        label: 'email › subject',
                        before: 'Old subject',
                        after: 'New subject',
                    },
                    { path: 'config.inputs.email.value.html', label: 'email › html', before: '<p>hi</p>', after: null },
                ],
            },
        ])
    })

    it.each([
        ['a step the live workflow does not have', { actions: [{ id: 'new_1', name: 'Added' }] }, null],
        ['no live workflow yet', { actions: [{ id: 'email_1', name: 'Added' }] }, null],
    ])('reads nothing as before for %s', (_name, content, expectedName) => {
        const changes = describeSuggestedChanges(content, _name.startsWith('no') ? null : live)
        expect(changes.steps[0].stepName).toBe(expectedName)
        expect(changes.steps[0].fields).toEqual([{ path: 'name', label: 'name', before: undefined, after: 'Added' }])
    })

    it('lists changes outside the steps against the live workflow', () => {
        const changes = describeSuggestedChanges({ name: 'Renamed' }, live)
        expect(changes.steps).toEqual([])
        expect(changes.workflow).toEqual([
            { path: 'name', label: 'name', before: 'Onboarding welcome', after: 'Renamed' },
        ])
    })
})
