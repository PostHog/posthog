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

    describe('realtime cohort status', () => {
        it('refreshes until the cohort is ready, past a failed check', async () => {
            const states = ['needs_attention', 'error', 'ready']
            let calls = 0
            useMocks({
                post: {
                    '/api/projects/:team_id/hog_flows/user_blast_radius/': async ({ request }) => {
                        // The recipient email check posts here too, with an extra condition.
                        const { filters } = (await request.json()) as { filters: { properties: unknown[] } }
                        if (filters.properties.length > 1) {
                            return [200, { affected: 0, total: 0 }]
                        }
                        const state = states[Math.min(calls++, states.length - 1)]
                        if (state === 'error') {
                            return [500, { detail: 'Simulated outage' }]
                        }
                        return [
                            200,
                            {
                                affected: 0,
                                total: 0,
                                realtime_cohort: { id: 42, name: 'Upgraded', state, percent_complete: null },
                            },
                        ]
                    },
                },
            })
            initKeaTests()
            const logic = batchTriggerLogic({
                id: 'realtime-status',
                filters: { properties: [{ key: 'id', type: 'cohort', value: 42, operator: 'in' }] as any },
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadBlastRadiusSuccess'])
            expect(logic.values.blastRadius?.realtime_cohort?.state).toEqual('needs_attention')

            jest.useFakeTimers()
            try {
                await jest.advanceTimersByTimeAsync(20000)
                await expectLogic(logic).toDispatchActions(['loadBlastRadiusSuccess'])
                expect(logic.values.blastRadius?.realtime_cohort?.state).toEqual('ready')

                await jest.advanceTimersByTimeAsync(30000)
                expect(calls).toEqual(3)
            } finally {
                jest.useRealTimers()
                logic.unmount()
            }
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
            {
                name: 'a filtered person',
                audience_type: 'persons' as const,
                properties: audience.properties,
                expected: { email: 98, $email: 0 },
            },
            { name: 'an account', audience_type: 'accounts' as const, properties: audience.properties, expected: {} },
            { name: 'an unfiltered person', audience_type: 'persons' as const, properties: [], expected: {} },
        ])('counts each To property for $name audience', async ({ audience_type, properties, expected }) => {
            const logic = batchTriggerLogic({
                id: `test-${audience_type}-${properties.length}`,
                filters: { properties, audience_type },
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

    describe('blastRadius', () => {
        it('drops a realtime cohort result when the next size check fails', async () => {
            let fail = false
            useMocks({
                post: {
                    '/api/projects/:team_id/hog_flows/user_blast_radius/': () =>
                        fail
                            ? [500, { detail: 'boom' }]
                            : [
                                  200,
                                  {
                                      affected: 3,
                                      total: 5,
                                      limit: 1000,
                                      dedupe_key: null,
                                      confirm_token: 'token',
                                      realtime_cohort: { id: 2, name: 'c', state: 'ready', percent_complete: null },
                                  },
                              ],
                },
            })
            initKeaTests()
            const logic = batchTriggerLogic({
                id: 'test-stale',
                filters: { properties: [{ key: 'id', type: 'cohort', value: 2, operator: 'in' }] as any },
            })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadBlastRadiusSuccess'])
            expect(logic.values.blastRadius?.realtime_cohort?.id).toBe(2)

            fail = true
            logic.actions.loadBlastRadius()
            await expectLogic(logic).toDispatchActions(['loadBlastRadiusFailure']).toMatchValues({ blastRadius: null })
            logic.unmount()
        })
    })
})
