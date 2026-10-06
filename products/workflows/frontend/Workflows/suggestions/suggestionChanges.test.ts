import type { HogFlow } from '../hogflows/types'
import { describeSuggestedChanges, groupStepFields } from './suggestionChanges'

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
                isNew: false,
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
        ['a step the live workflow does not have', { actions: [{ id: 'new_1', name: 'Added' }] }],
        ['no live workflow yet', { actions: [{ id: 'email_1', name: 'Added' }] }],
    ])('reads nothing as before for %s, and names the step from the suggestion', (_name, content) => {
        const changes = describeSuggestedChanges(content, _name.startsWith('no') ? null : live)
        expect(changes.steps[0]).toMatchObject({ stepName: 'Added', isNew: true })
        expect(changes.steps[0].fields).toEqual([{ path: 'name', label: 'name', before: undefined, after: 'Added' }])
    })

    it('lists changes outside the steps against the live workflow', () => {
        const changes = describeSuggestedChanges({ name: 'Renamed' }, live)
        expect(changes.steps).toEqual([])
        expect(changes.workflow).toEqual([
            { path: 'name', label: 'name', before: 'Onboarding welcome', after: 'Renamed' },
        ])
    })

    it('leaves out fields a whole-step patch resent unchanged', () => {
        const live = {
            actions: [{ id: 'email_1', name: 'Email', config: { subject: 'Old', from: 'a@example.com' } }],
        } as unknown as HogFlow

        const { steps } = describeSuggestedChanges(
            { actions: [{ id: 'email_1', name: 'Email', config: { subject: 'New', from: 'a@example.com' } }] },
            live
        )

        // Approving reduces the patch the same way, so the table must not read as a four-field edit.
        expect(steps[0].fields.map((field) => field.path)).toEqual(['config.subject'])
    })

    it.each([
        [
            'a new email step',
            null,
            {
                main: ['name', 'config.inputs.email.value.subject'],
                other: ['config.utm_tags_enabled', 'config.inputs.email.value.design.body.rows'],
            },
        ],
        [
            'an edited email step',
            {
                name: 'Welcome email',
                config: { inputs: { email: { value: { subject: 'Old', cc: 'a@example.com' } } } },
            },
            {
                main: [
                    'name',
                    'config.utm_tags_enabled',
                    'config.inputs.email.value.subject',
                    'config.inputs.email.value.preheader',
                    'config.inputs.email.value.cc',
                ],
                other: ['config.inputs.email.value.design.body.rows'],
            },
        ],
    ])('groups the fields of %s so the email and its key fields come first', (_name, liveStep, expected) => {
        const step = {
            id: 'email_2',
            name: 'Follow-up',
            config: {
                utm_tags_enabled: true,
                inputs: {
                    email: {
                        value: {
                            subject: 'Did you see this?',
                            preheader: '',
                            cc: '',
                            html: '<p>hi</p>',
                            design: { body: { rows: [{ id: 'row_1' }] } },
                        },
                    },
                },
            },
        }
        const workflow = { actions: liveStep ? [{ id: 'email_2', ...liveStep }] : [] } as unknown as HogFlow

        const grouped = groupStepFields(describeSuggestedChanges({ actions: [step] }, workflow).steps[0])

        expect(grouped.email.map((field) => field.path)).toEqual(['config.inputs.email.value.html'])
        expect(grouped.main.map((field) => field.path)).toEqual(expected.main)
        expect(grouped.other.map((field) => field.path)).toEqual(expected.other)
    })
})
