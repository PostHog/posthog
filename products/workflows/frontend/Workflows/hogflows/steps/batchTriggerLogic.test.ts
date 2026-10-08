import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlowAction } from '../types'
import { batchTriggerLogic, getAudienceDedupeKey } from './batchTriggerLogic'

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

describe('batchTriggerLogic', () => {
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
        ] as [string | null, string][])(
            'returns undefined when recipient is %j (%s) — avoids deduping on the wrong key',
            (template) => {
                expect(getAudienceDedupeKey({ actions: [emailAction(template)] })).toBeUndefined()
            }
        )

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

    describe('recipientsWithoutEmail', () => {
        const audience = { properties: [{ key: 'plan', value: 'pro', operator: 'exact', type: 'person' }] }

        beforeEach(() => {
            useMocks({
                post: {
                    '/api/projects/:team_id/hog_flows/user_blast_radius/': async ({ request }) => {
                        const { filters } = (await request.json()) as {
                            filters: { properties: { key: string; operator?: string }[] }
                        }
                        const last = filters.properties[filters.properties.length - 1]
                        const missing: Record<string, number> = { email: 98, $email: 0 }
                        return [
                            200,
                            { affected: last.operator === 'is_not_set' ? missing[last.key] : 100, total: 1000 },
                        ]
                    },
                },
            })
            initKeaTests()
        })

        it.each([
            { audience_type: 'persons' as const, expected: { email: 98, $email: 0 } },
            { audience_type: 'accounts' as const, expected: {} },
        ])('counts each To property for a $audience_type audience', async ({ audience_type, expected }) => {
            const logic = batchTriggerLogic({
                id: `test-${audience_type}`,
                filters: { ...audience, audience_type },
                sendsEmail: true,
                recipientEmailProperties: ['$email', 'email'],
            })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['loadRecipientsWithoutEmailSuccess'])
                .toMatchValues({ recipientsWithoutEmail: expected })
            logic.unmount()
        })
    })
})
