import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SourceSpendApi } from 'products/signals/frontend/generated/api.schemas'

import { usageOverviewLogic } from './usageOverviewLogic'

describe('usageOverviewLogic', () => {
    it.each([
        {
            name: 'groups source subtypes and combines scout signals with scout runs once',
            sources: [
                { source_product: 'error_tracking', source_type: 'issue_created', amount: 125 },
                { source_product: 'error_tracking', source_type: 'issue_spiking', amount: 25 },
                { source_product: 'signals_scout', source_type: 'cross_source_issue', amount: 13 },
                { source_product: 'llm_analytics', source_type: 'evaluation_report', amount: 0 },
                { source_product: 'linear', source_type: 'issue', amount: null },
            ],
            scoutAmount: 100,
            expected: [
                { sourceProduct: 'error_tracking', amount: 150 },
                { sourceProduct: 'signals_scout', amount: 113 },
                { sourceProduct: 'llm_analytics', amount: 0 },
                { sourceProduct: 'linear', amount: null },
            ],
        },
        {
            name: 'shows zero scout usage when there is no activity',
            sources: [],
            scoutAmount: 0,
            expected: [{ sourceProduct: 'signals_scout', amount: 0 }],
        },
        {
            name: 'preserves untracked scout usage',
            sources: [{ source_product: 'signals_scout', source_type: 'cross_source_issue', amount: null }],
            scoutAmount: null,
            expected: [{ sourceProduct: 'signals_scout', amount: null }],
        },
    ])('$name', async ({ sources, scoutAmount, expected }) => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:id/signals/source_spend/': sources.map(
                    ({ source_product, source_type, amount }): SourceSpendApi => ({
                        source_product,
                        source_type,
                        signal_count: 1,
                        spend: { total_spend: amount, incomplete: amount === null },
                    })
                ),
                '/api/projects/:id/signals/spend/': {
                    period_start: '2026-06-01T00:00:00Z',
                    period_end: '2026-07-01T00:00:00Z',
                    scout_spend: { total_spend: scoutAmount, incomplete: scoutAmount === null },
                    scouts: [],
                },
            },
        })
        const logic = usageOverviewLogic({ teamId: MOCK_DEFAULT_TEAM.id })
        logic.mount()
        try {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.buckets).toEqual(expected)
        } finally {
            logic.unmount()
        }
    })
})
