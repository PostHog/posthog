import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

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
})
