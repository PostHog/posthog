import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { BlastRadiusApi } from 'products/workflows/frontend/generated/api.schemas'

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

const FILTERS = { properties: [] }

const blastRadius = (affected: number): BlastRadiusApi =>
    ({ affected, total: 1000, limit: 5000, dedupe_key: null, confirm_token: 'token' }) as BlastRadiusApi

describe('batchTriggerLogic', () => {
    describe('blast radius loading', () => {
        let logic: ReturnType<typeof batchTriggerLogic.build>
        let resolvers: ((value: BlastRadiusApi) => void)[]
        let rejecters: ((reason: Error) => void)[]
        let requestSpy: jest.SpyInstance

        beforeEach(() => {
            resolvers = []
            rejecters = []
            requestSpy = jest.spyOn(api.hogFlows, 'getBatchTriggerBlastRadius').mockImplementation(
                () =>
                    new Promise<BlastRadiusApi>((resolve, reject) => {
                        resolvers.push(resolve)
                        rejecters.push(reject)
                    })
            )
            initKeaTests()
        })

        afterEach(() => {
            logic?.unmount()
            jest.restoreAllMocks()
        })

        // The panel mounts before the workflow loads, so the dedupe key and the email flag settle a
        // beat after the first request goes out. The two requests count different things against
        // different limits, so the older one must never land on top of the newer one.
        const startSupersededPair = async (id: string): Promise<void> => {
            logic = batchTriggerLogic({ id, filters: FILTERS })
            logic.mount()
            await waitFor(() => expect(requestSpy).toHaveBeenCalledTimes(1))

            batchTriggerLogic({ id, filters: FILTERS, dedupeKey: 'email', sendsEmail: true })
            await waitFor(() => expect(requestSpy).toHaveBeenCalledTimes(2))
        }

        it('keeps the newest count when a superseded request resolves last', async () => {
            await startSupersededPair('trigger-1')

            resolvers[1](blastRadius(42))
            await expectLogic(logic).toDispatchActions(['loadBlastRadiusSuccess'])
            expect(logic.values.blastRadius?.affected).toBe(42)

            resolvers[0](blastRadius(999))
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.blastRadius?.affected).toBe(42)
        })

        it('does not raise the validation warning when a superseded request rejects', async () => {
            await startSupersededPair('trigger-2')

            resolvers[1](blastRadius(7))
            await expectLogic(logic).toDispatchActions(['loadBlastRadiusSuccess'])

            rejecters[0](new Error('These filters cannot be evaluated.'))
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.blastRadiusError).toBeNull()
            expect(logic.values.blastRadius?.affected).toBe(7)
        })

        it('collapses the burst of prop changes on mount into one request', async () => {
            logic = batchTriggerLogic({ id: 'trigger-3', filters: FILTERS })
            logic.mount()
            batchTriggerLogic({ id: 'trigger-3', filters: FILTERS, sendsEmail: true })
            batchTriggerLogic({ id: 'trigger-3', filters: FILTERS, dedupeKey: 'email', sendsEmail: true })

            await waitFor(() => expect(requestSpy).toHaveBeenCalledTimes(1))
            expect(requestSpy).toHaveBeenCalledWith(FILTERS, 'email', true)
        })
    })

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
})
