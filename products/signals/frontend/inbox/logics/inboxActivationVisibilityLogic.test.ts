import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { InboxOnboardingStateApi } from '../../generated/api.schemas'
import { inboxActivationVisibilityLogic } from './inboxActivationVisibilityLogic'
import { inboxSetupLogic } from './inboxSetupLogic'

const ACTIVATED_AT = Date.parse('2026-10-01T12:00:00Z')
const SEVEN_DAYS = 7 * 24 * 60 * 60_000

describe('Inbox activation panel visibility', () => {
    let logic: ReturnType<typeof inboxActivationVisibilityLogic.build>
    let state: InboxOnboardingStateApi
    let reportCount: number
    let reportRequests: URLSearchParams[]
    let unmount: (() => void) | undefined

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        state = { variant: 'test-github', completed_at: new Date(ACTIVATED_AT).toISOString(), draft: null }
        reportCount = 0
        reportRequests = []
        unmount = undefined
        jest.spyOn(Date, 'now').mockReturnValue(ACTIVATED_AT)
        useMocks({
            get: {
                '/api/projects/:id/signals/onboarding/': () => [200, state],
                '/api/projects/:id/signals/reports/': ({ request }) => {
                    reportRequests.push(new URL(request.url).searchParams)
                    return [200, { count: reportCount, results: [], next: null, previous: null }]
                },
            },
        })
        logic = inboxActivationVisibilityLogic()
    })

    afterEach(() => {
        unmount?.()
        jest.restoreAllMocks()
    })

    async function checkVisibility(age: number): Promise<void> {
        jest.mocked(Date.now).mockReturnValue(ACTIVATED_AT + age)
        unmount ??= logic.mount()
        await expectLogic(inboxSetupLogic).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.checkVisibility()).toFinishAllListeners()
    }

    describe.each(['test-github', 'test-ui'] as const)('%s', (variant) => {
        it.each<[string, number, number, boolean]>([
            ['before seven days with reports', SEVEN_DAYS - 1, 1, true],
            ['at seven days with reports', SEVEN_DAYS, 1, false],
            ['after seven days without reports', SEVEN_DAYS + 60_000, 0, true],
        ])('%s', async (_name, age, count, visible) => {
            state = { ...state, variant }
            reportCount = count
            await checkVisibility(age)
            expect(logic.values.showActivationPanel).toBe(visible)
            if (age < SEVEN_DAYS) {
                expect(reportRequests).toHaveLength(0)
            } else {
                expect(reportRequests.length).toBeGreaterThan(0)
                expect(Object.fromEntries(reportRequests[0])).toEqual({
                    count_only: 'true',
                    scope: 'entire_project',
                    status: 'ready,resolved,pending_input,suppressed',
                })
            }
        })
    })

    it('hides when the first report arrives after seven days and stops requesting counts', async () => {
        await checkVisibility(SEVEN_DAYS)
        expect(logic.values.showActivationPanel).toBe(true)
        reportCount = 1
        await checkVisibility(SEVEN_DAYS + 60_000)
        expect(logic.values.showActivationPanel).toBe(false)
        const requestsAfterHiding = reportRequests.length
        await checkVisibility(SEVEN_DAYS + 120_000)
        expect(reportRequests).toHaveLength(requestsAfterHiding)
    })

    it.each(['control', null] as const)('does not show the panel or check reports for %s', async (variant) => {
        state = { ...state, variant }
        await checkVisibility(SEVEN_DAYS)
        expect(logic.values.showActivationPanel).toBe(false)
        expect(reportRequests).toHaveLength(0)
    })
})
