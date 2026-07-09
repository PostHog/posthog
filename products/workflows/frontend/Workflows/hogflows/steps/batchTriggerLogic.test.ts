import { HogFlowAction } from '../types'
import { getAudienceDedupeKey } from './batchTriggerLogic'

const emailAction = (toEmail: string | null): HogFlowAction =>
    ({
        id: 'email_1',
        type: 'function_email',
        name: 'Send email',
        config: {
            template_id: 'template-email',
            inputs:
                toEmail === null
                    ? {}
                    : {
                          email: {
                              value: {
                                  to: { email: toEmail, name: '' },
                                  from: {},
                                  subject: 'Hi',
                                  text: 'Hello',
                                  html: '<p>Hello</p>',
                              },
                          },
                      },
        },
    }) as any

describe('getAudienceDedupeKey', () => {
    it.each([
        ['{{ person.properties.email }}', 'email' as const],
        ['{{person.properties.email}}', 'email' as const],
        ['  {{  person.properties.email  }}  ', 'email' as const],
    ])('returns "email" for default recipient template %j', (template, expected) => {
        expect(getAudienceDedupeKey({ actions: [emailAction(template)] })).toBe(expected)
    })

    it.each([
        ['{{ person.properties.work_email }}', 'custom property'],
        ['{{ person.properties.email || person.properties.work_email }}', 'computed expression'],
        ['newsletter@example.com', 'static address'],
        ['', 'empty string'],
        [null, 'missing inputs (no email input at all)'],
    ])('returns undefined when recipient is %j (%s) — avoids deduping on the wrong key', (template) => {
        expect(getAudienceDedupeKey({ actions: [emailAction(template)] })).toBeUndefined()
    })

    it('returns undefined when there is no function_email action at all', () => {
        const nonEmailAction = { id: 'a1', type: 'function', config: {} } as any
        expect(getAudienceDedupeKey({ actions: [nonEmailAction] })).toBeUndefined()
        expect(getAudienceDedupeKey({ actions: [] })).toBeUndefined()
        expect(getAudienceDedupeKey({})).toBeUndefined()
        expect(getAudienceDedupeKey(null)).toBeUndefined()
    })

    it('returns undefined when any email action uses a non-default recipient — mixed workflows cannot dedupe consistently', () => {
        expect(
            getAudienceDedupeKey({
                actions: [
                    emailAction('{{ person.properties.email }}'),
                    emailAction('{{ person.properties.work_email }}'),
                ],
            })
        ).toBeUndefined()
    })
})
