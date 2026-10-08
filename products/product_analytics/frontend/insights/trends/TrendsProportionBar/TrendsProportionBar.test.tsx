import '@testing-library/jest-dom'

import { cleanup, waitFor } from '@testing-library/react'

import { getHogChart, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, renderInsight } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

describe('TrendsProportionBar', () => {
    it.each([
        {
            name: 'shows the legend with each share by default, because the bar has no axis',
            showLegend: undefined,
            expectedRows: [
                { label: 'Spike', secondaryLabel: '57.9% · 11' },
                { label: 'Thistle', secondaryLabel: '21.1% · 4' },
                { label: 'Bramble', secondaryLabel: '10.5% · 2' },
                { label: 'Prickles', secondaryLabel: '10.5% · 2' },
                { label: 'Conker', secondaryLabel: '0% · 0' },
            ],
        },
        { name: 'hides the legend when the user turns it off', showLegend: false, expectedRows: [] },
        {
            name: 'starts with the legend off when there are many parts',
            event: 'NappedByManyHedgehogs',
            showLegend: undefined,
            expectedRows: [],
        },
    ])('$name', async ({ event = 'Napped', showLegend, expectedRows }) => {
        const { container } = renderInsight({
            query: buildTrendsQuery({
                series: [{ kind: NodeKind.EventsNode, event, name: event }],
                breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                trendsFilter: { display: ChartDisplayType.ActionsProportionBar, showLegend },
            }),
        })
        await waitFor(() => expect(container.querySelector('[data-attr="trend-proportion-bar"]')).not.toBeNull(), {
            timeout: 5000,
        })

        expect(getHogChart(container).legendItems()).toEqual(expectedRows)
    })

    it('floors a negative part at 0 in the total below the bar, matching what the bar renders', async () => {
        const { container } = renderInsight({
            query: buildTrendsQuery({
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'NappedWithNegativePart',
                        name: 'NappedWithNegativePart',
                    },
                ],
                breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
                trendsFilter: { display: ChartDisplayType.ActionsProportionBar },
            }),
        })
        await waitFor(() => expect(container.querySelector('[data-attr="trend-proportion-bar"]')).not.toBeNull(), {
            timeout: 5000,
        })

        // The bar floors -4 at 0, so the total reads 10, not the raw sum of 6.
        expect(container.querySelector('[data-attr="trend-total"]')).toHaveTextContent('10')
    })

    it('leaves the previous period out of a bar saved with compare on', async () => {
        const { container } = renderInsight({
            query: buildTrendsQuery({
                series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
                trendsFilter: { display: ChartDisplayType.ActionsProportionBar },
                compareFilter: { compare: true },
            }),
        })
        await waitFor(() => expect(container.querySelector('[data-attr="trend-proportion-bar"]')).not.toBeNull(), {
            timeout: 5000,
        })

        expect(getHogChart(container).legendItems()).toHaveLength(1)
    })
})
