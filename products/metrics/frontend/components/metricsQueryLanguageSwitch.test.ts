import posthog from 'posthog-js'

import { LemonDialog } from '@posthog/lemon-ui'

import { MetricsQuery, NodeKind } from '~/queries/schema/schema-general'

import { switchMetricsQueryLanguage } from './metricsQueryLanguageSwitch'

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonDialog: { open: jest.fn() },
}))

const builderQuery = (fields: Partial<MetricsQuery['clauses'][number]> = {}): MetricsQuery => ({
    kind: NodeKind.MetricsQuery,
    clauses: [{ name: 'a', metricName: 'queue_depth', aggregation: 'sum', ...fields }],
    dateRange: { date_from: '-1h' },
})

describe('switchMetricsQueryLanguage', () => {
    beforeEach(() => {
        jest.mocked(LemonDialog.open).mockClear()
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    it('switches a lossless conversion without asking', () => {
        const apply = jest.fn()
        switchMetricsQueryLanguage(builderQuery(), 'promql', apply)

        expect(LemonDialog.open).not.toHaveBeenCalled()
        expect(apply).toHaveBeenCalledWith({
            kind: NodeKind.MetricsQuery,
            clauses: [],
            language: 'promql',
            promql: 'sum(queue_depth)',
            dateRange: { date_from: '-1h' },
        })
        expect(posthog.capture).toHaveBeenCalledWith('metrics query language switched', {
            from: 'builder',
            to: 'promql',
            lossy: false,
            issue_count: 0,
            confirmed: true,
        })
    })

    it('asks before a lossy conversion and keeps the query on cancel', () => {
        const apply = jest.fn()
        switchMetricsQueryLanguage(
            builderQuery({ filters: [{ key: 'host.name', op: 'eq', value: 'a', scope: 'resource' }] }),
            'promql',
            apply
        )

        expect(apply).not.toHaveBeenCalled()
        const dialog = jest.mocked(LemonDialog.open).mock.calls[0][0]
        ;(dialog.secondaryButton?.onClick as () => void)()
        expect(apply).not.toHaveBeenCalled()
        expect(posthog.capture).toHaveBeenCalledWith(
            'metrics query language switched',
            expect.objectContaining({ lossy: true, confirmed: false })
        )

        ;(dialog.primaryButton?.onClick as () => void)()
        expect(apply).toHaveBeenCalledWith(expect.objectContaining({ language: 'promql' }))
    })
})
