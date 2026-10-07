import { withTestEmailRecipient } from './emailTestSend'
import { HogFlowAction } from './Workflows/hogflows/types'

const action = (partial: Partial<HogFlowAction>): HogFlowAction =>
    ({
        id: 'step',
        name: 'Step',
        description: '',
        created_at: 0,
        updated_at: 0,
        ...partial,
    }) as HogFlowAction

const emailAction = action({
    type: 'function_email',
    config: {
        template_id: 'template-email',
        inputs: {
            email: {
                value: {
                    to: { email: '{{ person.properties.email }}', name: '{{ person.properties.name }}' },
                    cc: 'team@example.com',
                    bcc: 'archive@example.com',
                    from: { integrationId: 7 },
                    subject: 'Welcome',
                    html: '<p>Hello</p>',
                },
                templating: 'liquid',
            },
        },
    },
})

describe('withTestEmailRecipient', () => {
    it('sends to the tester alone and keeps the rest of the email', () => {
        const testAction = withTestEmailRecipient(emailAction, 'tester@example.com')

        expect(testAction).toEqual({
            ...emailAction,
            config: {
                template_id: 'template-email',
                inputs: {
                    email: {
                        value: {
                            to: { email: 'tester@example.com', name: '' },
                            cc: '',
                            bcc: '',
                            from: { integrationId: 7 },
                            subject: 'Welcome',
                            html: '<p>Hello</p>',
                        },
                        templating: 'liquid',
                    },
                },
            },
        })
    })

    it('leaves a step that sends no email untouched', () => {
        const delay = action({ type: 'delay', config: { delay_duration: '1d' } })

        expect(withTestEmailRecipient(delay, 'tester@example.com')).toBe(delay)
    })
})
