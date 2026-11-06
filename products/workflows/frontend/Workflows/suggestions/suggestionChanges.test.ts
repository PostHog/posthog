import type { HogFlow } from '../hogflows/types'
import { SuggestedFieldView, describeFieldView, describeSuggestedChanges, groupStepFields } from './suggestionChanges'

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

    it.each([
        ['the same image, so only the text changes', 'A', 'A', false],
        ['a swapped image of the same size', 'A', 'B', true],
    ])('shows an inline image as its size and digest: %s', (_name, beforeFill, afterFill, imageLineDiffers) => {
        const html = (fill: string, cta: string): string =>
            `<p>Hi</p><img src="data:image/png;base64,${fill.repeat(4096)}"><a>${cta}</a>`

        const view = describeFieldView({
            path: 'config.inputs.email.value.html',
            label: 'email › html',
            before: html(beforeFill, 'Old'),
            after: html(afterFill, 'New'),
        })

        const { original, modified } = view as Extract<SuggestedFieldView, { kind: 'diff' }>
        const imageLine = (text: string): string => text.split('\n')[1]
        expect(imageLine(original)).toMatch(/^<img src="data:image\/png;base64,… \(3 KB, [0-9a-f]{8}\)">$/)
        expect(imageLine(original) !== imageLine(modified)).toBe(imageLineDiffers)
    })
})
