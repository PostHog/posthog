import type { HogFlow } from '../hogflows/types'
import { describeFieldView, describeSuggestedChanges } from './suggestionChanges'

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

describe('suggestionChanges', () => {
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

    describe('describeFieldView', () => {
        const emailHtml = (cta: string): string =>
            `<table><tr><td><h1>Welcome aboard</h1></td></tr><tr><td><a href="https://example.com/start">${cta}</a></td></tr></table>`

        it.each([
            [
                'a short text edit',
                'config.inputs.email.value.subject',
                'Old subject',
                'New subject',
                { kind: 'inline' },
            ],
            ['a number', 'config.delay_duration', 1, 2, { kind: 'inline' }],
            [
                'minified email HTML, split between tags',
                'config.inputs.email.value.html',
                emailHtml('Run the play'),
                emailHtml('Create your first workflow'),
                {
                    kind: 'diff',
                    language: 'html',
                    original: emailHtml('Run the play').replace(/>(?=<)/g, '>\n'),
                    modified: emailHtml('Create your first workflow').replace(/>(?=<)/g, '>\n'),
                },
            ],
            [
                'a new multi-line text field',
                'config.inputs.email.value.text',
                undefined,
                'Hi there\nYour trial ends soon',
                { kind: 'diff', language: 'plaintext', original: '', modified: 'Hi there\nYour trial ends soon' },
            ],
            [
                'an object',
                'filters',
                { events: [{ id: 'signed_up' }] },
                { events: [{ id: 'signed_up' }, { id: 'invited_user' }] },
                {
                    kind: 'diff',
                    language: 'json',
                    original: JSON.stringify({ events: [{ id: 'signed_up' }] }, null, 2),
                    modified: JSON.stringify({ events: [{ id: 'signed_up' }, { id: 'invited_user' }] }, null, 2),
                },
            ],
        ])('shows %s as the right view', (_name, path, before, after, expected) => {
            expect(describeFieldView({ path, label: path, before, after })).toEqual(expected)
        })
    })
})
