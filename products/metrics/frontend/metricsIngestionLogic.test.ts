import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsHasMetricsRetrieve } from './generated/api'
import { metricsIngestionLogic } from './metricsIngestionLogic'

jest.mock('./generated/api', () => ({
    metricsHasMetricsRetrieve: jest.fn(),
}))

describe('metricsIngestionLogic', () => {
    let logic: ReturnType<typeof metricsIngestionLogic.build>

    // teamLogic is mounted via connect once `logic` mounts, so its actionCreators are available here.
    const firstIngestIntent = (): any =>
        teamLogic.actionCreators.addProductIntent({
            product_type: ProductKey.METRICS,
            intent_context: ProductIntentContext.METRICS_FIRST_INGESTED,
        })

    beforeEach(() => {
        localStorage.clear()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
            },
        } as AppContext
        initKeaTests()
        jest.mocked(metricsHasMetricsRetrieve).mockReset()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // Distinguishes a team completing OTel setup mid-session (intent) from a team that simply
    // already had metrics (no intent) — firing on any `true` would mark every long-standing
    // team as newly intending and corrupt the activation funnel.
    it('records a product intent only on an observed no-metrics -> has-metrics transition, once', async () => {
        jest.mocked(metricsHasMetricsRetrieve).mockResolvedValue({ hasMetrics: false } as any)
        logic = metricsIngestionLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadTeamHasMetricsSuccess'])
            .toNotHaveDispatchedActions([firstIngestIntent()])

        jest.mocked(metricsHasMetricsRetrieve).mockResolvedValue({ hasMetrics: true } as any)
        await expectLogic(logic, () => {
            logic.actions.loadTeamHasMetrics()
        }).toDispatchActions([firstIngestIntent()])

        await expectLogic(logic, () => {
            logic.actions.loadTeamHasMetrics()
        }).toNotHaveDispatchedActions([firstIngestIntent()])
    })

    it('a team that already has metrics on first check records no intent', async () => {
        jest.mocked(metricsHasMetricsRetrieve).mockResolvedValue({ hasMetrics: true } as any)
        logic = metricsIngestionLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadTeamHasMetricsSuccess'])
            .toNotHaveDispatchedActions([firstIngestIntent()])
    })

    it('does not check ingestion without metrics viewer access', async () => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.None,
            },
        } as AppContext
        logic = metricsIngestionLogic()
        logic.mount()

        await expectLogic(logic).delay(10)

        expect(metricsHasMetricsRetrieve).not.toHaveBeenCalled()

        // A denied check must stay "unknown", not become "no metrics" - false would
        // show the setup prompt to a user on a team that may have plenty of metrics.
        await expectLogic(logic, () => {
            logic.actions.loadTeamHasMetrics()
        }).toFinishAllListeners()

        expect(metricsHasMetricsRetrieve).not.toHaveBeenCalled()
        expect(logic.values.hasMetrics).toBeUndefined()
    })
})
