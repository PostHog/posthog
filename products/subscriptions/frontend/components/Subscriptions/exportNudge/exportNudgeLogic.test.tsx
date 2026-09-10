import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { userLogic } from 'scenes/userLogic'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { SubscriptionFreeTierLimit } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, InsightShortId, UserType } from '~/types'

import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'
import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'

import {
    claimExportNudge,
    exportNudgeLogic,
    lookUpExportNudge,
    resolveExportNudgeEligibility,
} from './exportNudgeLogic'
import { ExportNudgeSubject } from './exportNudgeSubject'
import { claimExportNudgeMessage } from './ExportNudgeToast'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { capture: jest.fn(), captureRaw: jest.fn() },
}))

jest.mock('products/subscriptions/frontend/generated/api', () => ({
    subscriptionsList: jest.fn(),
}))

const mockSubscriptionsList = subscriptionsList as jest.Mock

const DASHBOARD_ID = 1
const INSIGHT_SHORT_ID = '11' as InsightShortId
const DASHBOARD: ExportNudgeSubject = { kind: 'dashboard', dashboardId: DASHBOARD_ID }
const INSIGHT: ExportNudgeSubject = { kind: 'insight', insightShortId: INSIGHT_SHORT_ID }

const USER_WITH_SUBSCRIPTIONS_FEATURE: UserType = {
    ...MOCK_DEFAULT_USER,
    organization: {
        ...MOCK_DEFAULT_ORGANIZATION,
        available_product_features: [{ key: AvailableFeature.SUBSCRIPTIONS, name: 'Subscriptions' }],
    },
}

function capturesOf(event: string): any[][] {
    return [...(posthog.capture as jest.Mock).mock.calls, ...(posthog.captureRaw as jest.Mock).mock.calls].filter(
        ([name]) => name === event
    )
}

describe('exportNudgeLogic', () => {
    let logic: ReturnType<typeof exportNudgeLogic.build>

    function mockSubscriptionCounts({
        subjectCount,
        teamCount = 0,
    }: {
        subjectCount: number
        teamCount?: number
    }): void {
        mockSubscriptionsList.mockImplementation((_teamId: string, params?: Record<string, unknown>) =>
            Promise.resolve(
                params?.dashboard || params?.insight
                    ? { count: subjectCount, results: [] }
                    : { count: teamCount, results: [] }
            )
        )
    }

    beforeEach(() => {
        window.localStorage.clear()
        mockSubscriptionsList.mockReset()
        mockSubscriptionCounts({ subjectCount: 0 })
        useMocks({
            get: {
                // Resolves the short id the insight subscription filter needs.
                '/api/environments/:team_id/insights': () => [200, { results: [{ id: 11, short_id: '11' }] }],
                '/api/environments/:team_id/subscriptions': () => [200, { results: [], count: 0 }],
            },
        })
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(USER_WITH_SUBSCRIPTIONS_FEATURE)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.DASHBOARD_EXPORT_NUDGE]: 'test',
            [FEATURE_FLAGS.INSIGHT_EXPORT_NUDGE]: 'test',
        })
        logic = exportNudgeLogic()
        logic.mount()
        ;(posthog.capture as jest.Mock).mockClear()
        ;(posthog.captureRaw as jest.Mock).mockClear()
    })

    afterEach(() => {
        logic.unmount()
        window.localStorage.clear()
    })

    async function considerNudge(subject: ExportNudgeSubject = DASHBOARD): Promise<boolean> {
        const candidate = await resolveExportNudgeEligibility(subject)
        return !!candidate && claimExportNudge(subject)
    }

    it.each([
        ['dashboard', DASHBOARD, { kind: 'dashboard', dashboard_id: DASHBOARD_ID }],
        ['insight', INSIGHT, { kind: 'insight', insight_short_id: INSIGHT_SHORT_ID }],
    ])('nudges an eligible %s exporter in the test variant', async (kind, subject, eventProperties) => {
        expect(await considerNudge(subject)).toBe(true)

        expect(capturesOf(`${kind} export nudge shown`)).toEqual([[`${kind} export nudge shown`, eventProperties]])
    })

    it('does not nudge in the control variant', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_EXPORT_NUDGE]: 'control' })

        // The variant is read only by the second half, so a control exporter still resolves as a
        // candidate. Every other check has to run before the flag read reports exposure.
        expect(await resolveExportNudgeEligibility(DASHBOARD)).toMatchObject({ subject: DASHBOARD })
        expect(claimExportNudge(DASHBOARD)).toBe(false)
    })

    it('nudges the same dashboard again on a later export', async () => {
        expect(await considerNudge()).toBe(true)
        expect(await considerNudge()).toBe(true)

        expect(capturesOf('dashboard export nudge shown')).toHaveLength(2)
    })

    it.each([
        ['dashboard', DASHBOARD, { kind: 'dashboard', dashboard_id: DASHBOARD_ID }],
        ['insight', INSIGHT, { kind: 'insight', insight_short_id: INSIGHT_SHORT_ID }],
    ])('does not nudge a %s that already has a subscription', async (_kind, subject, eventProperties) => {
        mockSubscriptionCounts({ subjectCount: 1 })

        expect(await considerNudge(subject)).toBe(false)
        expect(capturesOf('export nudge not eligible')).toEqual([
            ['export nudge not eligible', { reason: 'already_subscribed', ...eventProperties }],
        ])
    })

    it('asks again once the subscription that retired the offer is gone', async () => {
        mockSubscriptionCounts({ subjectCount: 1 })
        expect(await considerNudge()).toBe(false)

        // Nothing is remembered across the two exports: the subscription check is the only gate, so
        // deleting the subscription brings the offer back.
        mockSubscriptionCounts({ subjectCount: 0 })
        expect(await considerNudge()).toBe(true)
    })

    it('offers nothing it cannot check when the insight cannot be resolved', async () => {
        // A deleted insight, or an export racing its creation: the short id resolves to nothing, so
        // there is no subscription to check against.
        useMocks({ get: { '/api/environments/:team_id/insights': () => [200, { results: [] }] } })

        expect(await considerNudge(INSIGHT)).toBe(true)
        // The lookup answers "no subscription", which is what an unresolvable insight means here.
        expect(mockSubscriptionsList).not.toHaveBeenCalledWith(
            expect.anything(),
            expect.objectContaining({ insight: expect.anything() })
        )
    })

    describe('answering without a request', () => {
        // The scene mounts subscriptionsLogic to render the subscribe button's count badge, so most
        // exports can put the offer in their toast from the first frame instead of fetching again.
        it('is eligible off the subscriptions the scene already loaded', async () => {
            const sceneLogic = subscriptionsLogic({ dashboardId: DASHBOARD_ID })
            sceneLogic.mount()
            await expectLogic(sceneLogic).toFinishAllListeners()

            expect(lookUpExportNudge(DASHBOARD)).toMatchObject({ status: 'eligible' })
            expect(mockSubscriptionsList).not.toHaveBeenCalled()

            sceneLogic.unmount()
        })

        it('says so when nothing is loaded, rather than guessing', () => {
            expect(lookUpExportNudge(DASHBOARD)).toEqual({ status: 'unknown' })
        })

        it('is ineligible when the loaded subscriptions include one for the subject', () => {
            const sceneLogic = subscriptionsLogic({ dashboardId: DASHBOARD_ID })
            sceneLogic.mount()
            sceneLogic.actions.loadSubscriptionsSuccess([{ id: 1 } as any])

            expect(lookUpExportNudge(DASHBOARD)).toEqual({ status: 'ineligible' })
            expect(capturesOf('export nudge not eligible')).toEqual([
                [
                    'export nudge not eligible',
                    { reason: 'already_subscribed', kind: 'dashboard', dashboard_id: DASHBOARD_ID },
                ],
            ])

            sceneLogic.unmount()
        })

        it('is ineligible over the free-tier subscription limit', () => {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER) // no available features -> free tier
            logic.actions.loadFreeTierSubscriptionCountSuccess(SubscriptionFreeTierLimit.COUNT)

            expect(lookUpExportNudge(DASHBOARD)).toEqual({ status: 'ineligible' })
            expect(capturesOf('export nudge not eligible')).toEqual([
                ['export nudge not eligible', { reason: 'over_limit', kind: 'dashboard', dashboard_id: DASHBOARD_ID }],
            ])
        })
    })

    describe('free-tier subscription limit', () => {
        beforeEach(() => {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER) // no available features -> free tier
        })

        it.each([
            [0, true],
            [SubscriptionFreeTierLimit.COUNT - 1, true],
            [SubscriptionFreeTierLimit.COUNT, false],
        ])('with %i existing team subscriptions, nudges=%s', async (teamCount, nudges) => {
            mockSubscriptionCounts({ subjectCount: 0, teamCount })

            expect(await considerNudge()).toBe(nudges)
            expect(capturesOf('export nudge not eligible')).toEqual(
                nudges
                    ? []
                    : [
                          [
                              'export nudge not eligible',
                              { reason: 'over_limit', kind: 'dashboard', dashboard_id: DASHBOARD_ID },
                          ],
                      ]
            )
        })
    })

    describe('failed eligibility checks', () => {
        beforeEach(() => {
            silenceKeaLoadersErrors()
        })

        afterEach(() => {
            resumeKeaLoadersErrors()
        })

        it('fails closed and reports when the subscription check breaks', async () => {
            mockSubscriptionsList.mockRejectedValue({ name: 'ApiError', status: 500, message: 'boom' })

            expect(await considerNudge()).toBe(false)
            expect(capturesOf('export nudge check failed')).toHaveLength(1)
            expect(capturesOf('export nudge check failed')[0][1]).toMatchObject({
                dashboard_id: DASHBOARD_ID,
                step: 'check',
            })
        })

        it('fails closed and reports when the free-tier count breaks', async () => {
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
            mockSubscriptionsList.mockRejectedValue({ name: 'ApiError', status: 500, message: 'boom' })

            expect(await considerNudge()).toBe(false)
            expect(capturesOf('export nudge check failed')[0][1]).toMatchObject({ step: 'limit' })
        })
    })

    describe('nudge toast message', () => {
        afterEach(() => {
            cleanup()
        })

        it('renders nothing for an exporter outside the test variant', () => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.DASHBOARD_EXPORT_NUDGE]: 'control' })

            expect(claimExportNudgeMessage({ subject: DASHBOARD, name: 'Weekly numbers' })).toBeNull()
        })

        it.each([
            [DASHBOARD, 'Weekly numbers', `/dashboard/${DASHBOARD_ID}/subscriptions/new`],
            [INSIGHT, null, `/insights/${INSIGHT_SHORT_ID}/subscriptions/new`],
        ])('the CTA routes to the prefilled new-subscription form', (subject, name, path) => {
            const message = claimExportNudgeMessage({ subject, name })
            render(<>{message!('Export complete!', 'export-toast')}</>)

            fireEvent.click(screen.getByText('Subscribe'))

            expect(router.values.location.pathname).toMatch(new RegExp(`${path}$`))
            expect(router.values.searchParams).toMatchObject({ prefill: 'nudge', via: 'export' })
        })

        it('reports one follow even if the CTA is clicked twice', () => {
            // A toast held open by an undelivered file keeps this button on screen, and the offer
            // only leaves on a later frame, so nothing else stops a second click.
            const message = claimExportNudgeMessage({ subject: DASHBOARD, name: 'Weekly numbers' })
            render(<>{message!('Export complete!', 'export-toast')}</>)

            const push = jest.spyOn(router.actions, 'push')
            const cta = screen.getByText('Subscribe')
            fireEvent.click(cta)
            fireEvent.click(cta)

            expect(push).toHaveBeenCalledTimes(1)
            push.mockRestore()
        })

        it('drops the offer from later frames once it has been followed', () => {
            const message = claimExportNudgeMessage({ subject: DASHBOARD, name: 'Weekly numbers' })
            render(<>{message!('Preparing export…', 'export-toast')}</>)
            fireEvent.click(screen.getByText('Subscribe'))
            cleanup()

            // The export settles into its own message rather than asking a second time.
            expect(message!('Export complete!', 'export-toast')).toEqual('Export complete!')
        })
    })
})
