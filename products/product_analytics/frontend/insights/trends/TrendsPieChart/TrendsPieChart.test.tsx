import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { mockRect, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { NodeKind } from '~/queries/schema/schema-general'
import { buildTrendsQuery, legend, personsModal, renderInsight } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom(NARROW_RECT)
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    personsModal.cleanupAll()
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

function sliceLabels(): string[] {
    return Array.from(document.querySelectorAll('[data-attr="hog-chart-pie-slice-label"]')).map(
        (el) => el.textContent ?? ''
    )
}

// The default 800px-wide mock rect is "wide"; this one puts containers below the side-legend
// threshold so tests cover the narrow dashboard-tile layout.
const NARROW_RECT = { ...mockRect, width: 300 } as DOMRect

// jsdom's ResizeObserver stub never fires its callback, so layout hooks that wait on an entry
// would never resolve. Replace it with one that delivers a contentRect entry for the observed
// element immediately.
function setupResizeObserverRect(rect: DOMRect): () => void {
    const Original = global.ResizeObserver
    global.ResizeObserver = class {
        constructor(callback: ResizeObserverCallback) {
            setTimeout(
                () => callback([{ contentRect: rect } as ResizeObserverEntry], this as unknown as ResizeObserver),
                0
            )
        }
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
    } as unknown as typeof ResizeObserver
    return () => {
        global.ResizeObserver = Original
    }
}

// Napped × hedgehog fixture: Spike 11, Thistle 4, Bramble 2, Prickles 2, Conker 0.
// Conker drops out (0% < the 5% slice-label threshold); total of the rest is 19,
// so percent mode renders 11/19, 4/19, 2/19, 2/19.
const pieByHedgehog = (trendsFilter: Record<string, unknown> = {}): ReturnType<typeof buildTrendsQuery> =>
    buildTrendsQuery({
        series: [{ kind: NodeKind.EventsNode, event: 'Napped', name: 'Napped' }],
        breakdownFilter: { breakdown: 'hedgehog', breakdown_type: 'event' },
        trendsFilter: { display: ChartDisplayType.ActionsPie, showValuesOnSeries: true, ...trendsFilter },
    })

describe('TrendsPieChart (ActionsPie)', () => {
    it.each([
        {
            name: 'shows raw slice values when percent stack view is off',
            query: pieByHedgehog(),
            expectedLabels: ['11', '4', '2', '2'],
        },
        {
            name: 'formats slice values as percentages in percent stack view',
            query: pieByHedgehog({ showValuesOnSeries: false, showPercentStackView: true }),
            expectedLabels: ['57.9%', '21.1%', '10.5%', '10.5%'],
        },
        {
            name: 'shows the value and the percentage together when both options are on',
            query: pieByHedgehog({ showPercentStackView: true }),
            expectedLabels: ['11 (57.9%)', '4 (21.1%)', '2 (10.5%)', '2 (10.5%)'],
        },
        {
            // Name and value are separate lines, so a slice's text content reads as name then value.
            name: 'prefixes the slice with its name when labels on series is on',
            query: pieByHedgehog({ showLabelsOnSeries: true }),
            expectedLabels: ['Spike11', 'Thistle4', 'Bramble2', 'Prickles2'],
        },
    ])('$name', async ({ query, expectedLabels }) => {
        renderInsight({ query })
        await screen.findByLabelText(/pie chart with/i, undefined, { timeout: 5000 })

        await waitFor(
            () => {
                expect(sliceLabels().length).toBeGreaterThan(0)
            },
            { timeout: 5000 }
        )
        expect([...sliceLabels()].sort()).toEqual([...expectedLabels].sort())
    })

    describe('quill in-chart legend', () => {
        const getInChartLegend = (container: HTMLElement): HTMLElement | null =>
            container.querySelector<HTMLElement>('[data-attr="hog-chart-pie-legend"]')

        it('renders the in-chart legend and suppresses the legacy side legend', async () => {
            const { container } = renderInsight({ query: pieByHedgehog({ showLegend: true }) })
            await screen.findByLabelText(/pie chart with/i, undefined, { timeout: 5000 })

            const legendEl = getInChartLegend(container)
            expect(legendEl).not.toBeNull()
            expect(legendEl!.textContent).toContain('Spike')
            expect(container.querySelector('.InsightLegendMenu')).not.toBeInTheDocument()
        })

        it('humanizes built-in event names in the legend (no breakdown)', async () => {
            const { container } = renderInsight({
                query: buildTrendsQuery({
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
                    trendsFilter: { display: ChartDisplayType.ActionsPie, showLegend: true },
                }),
            })
            await screen.findByLabelText(/pie chart with/i, undefined, { timeout: 5000 })

            const legendEl = getInChartLegend(container)
            expect(legendEl).not.toBeNull()
            expect(legendEl!.textContent).toContain('Pageview')
            expect(legendEl!.textContent).not.toContain('$pageview')
        })

        it('removes a toggled-off slice but keeps it listed (dimmed) so it can be restored', async () => {
            const { container } = renderInsight({ query: pieByHedgehog({ showLegend: true }) })
            await screen.findByLabelText(/pie chart with 5 slices/i, undefined, { timeout: 5000 })

            await legend.toggle('Spike')

            await waitFor(() => {
                expect(screen.getByLabelText(/pie chart with 4 slices/i)).toBeInTheDocument()
            })
            const dimmed = [...getInChartLegend(container)!.querySelectorAll<HTMLElement>('button')].filter((b) =>
                b.className.includes('opacity-40')
            )
            expect(dimmed.map((b) => b.textContent)).toEqual(['Spike'])
        })

        // The chart wrapper's grandparent is the ChartLegendLayout root (its parent is the
        // layout's chart slot); its flex direction says whether the legend sits beside the
        // pie (row) or below it (column).
        const legendLayout = (container: HTMLElement): HTMLElement | null =>
            container.querySelector<HTMLElement>('[data-attr="trend-pie-graph"]')?.parentElement?.parentElement ?? null

        it('moves the default right legend below the pie in a narrow container', async () => {
            const restoreObserver = setupResizeObserverRect(NARROW_RECT)
            try {
                const { container } = renderInsight({ query: pieByHedgehog({ showLegend: true }) })
                await screen.findByLabelText(/pie chart with/i, undefined, { timeout: 5000 })
                await waitFor(() => {
                    expect(legendLayout(container)).toHaveClass('flex-col')
                })
            } finally {
                restoreObserver()
            }
        })

        it('keeps the default right legend beside the pie in a wide container', async () => {
            const restoreObserver = setupResizeObserverRect(mockRect)
            try {
                const { container } = renderInsight({ query: pieByHedgehog({ showLegend: true }) })
                await screen.findByLabelText(/pie chart with/i, undefined, { timeout: 5000 })
                await waitFor(() => {
                    expect(legendLayout(container)).toHaveClass('flex-row')
                })
            } finally {
                restoreObserver()
            }
        })
    })
})
