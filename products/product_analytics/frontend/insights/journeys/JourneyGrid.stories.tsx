import { Meta, StoryObj } from '@storybook/react'

import { PathsV2Results } from '~/queries/schema/schema-general'

import { JourneyGrid } from './JourneyGrid'
import { buildJourneyGridModel, chainCardKey, journeyItemKey, journeyRibbonKey } from './journeyGridModel'

const item = (event: string, label?: string): { event: string; label?: string } =>
    label === undefined ? { event } : { event, label }

const signUp = item('signed_up')
const dashboardView = item('$pageview', '/dashboard')
const pricingView = item('$pageview', '/pricing')
const ordersView = item('$pageview', '/orders')
const productViewed = item('product_viewed')
const productAdded = item('product_added')
const checkoutStarted = item('checkout_started')
const purchaseCompleted = item('purchase_completed')

// Drop-offs register at the journey's last reached step, so each column's drop-off count is a
// subset of that column's population (matching the runner's drop_off_elements semantics).
const MOCK_RESULTS: PathsV2Results = {
    steps: [
        { stepIndex: 0, rows: [{ item: signUp, count: 8240 }], otherCount: 0, dropOffCount: 2340 },
        {
            stepIndex: 1,
            rows: [
                { item: dashboardView, count: 2140 },
                { item: productViewed, count: 1350 },
                { item: checkoutStarted, count: 950 },
                { item: pricingView, count: 640 },
            ],
            otherCount: 820,
            dropOffCount: 2335,
        },
        {
            stepIndex: 2,
            rows: [
                { item: productAdded, count: 1400 },
                { item: checkoutStarted, count: 820 },
                { item: ordersView, count: 615 },
            ],
            otherCount: 690,
            dropOffCount: 1915,
        },
        {
            stepIndex: 3,
            rows: [
                { item: purchaseCompleted, count: 880 },
                { item: productAdded, count: 320 },
            ],
            otherCount: 410,
            dropOffCount: 1320,
        },
    ],
    edges: [
        { stepIndex: 0, source: signUp, target: dashboardView, count: 2140 },
        { stepIndex: 0, source: signUp, target: productViewed, count: 1350 },
        { stepIndex: 0, source: signUp, target: checkoutStarted, count: 950 },
        { stepIndex: 0, source: signUp, target: pricingView, count: 640 },
        { stepIndex: 0, source: signUp, target: null, count: 820 },
        { stepIndex: 1, source: dashboardView, target: productAdded, count: 700 },
        { stepIndex: 1, source: dashboardView, target: checkoutStarted, count: 260 },
        { stepIndex: 1, source: dashboardView, target: ordersView, count: 210 },
        { stepIndex: 1, source: dashboardView, target: null, count: 240 },
        { stepIndex: 1, source: productViewed, target: productAdded, count: 520 },
        { stepIndex: 1, source: productViewed, target: checkoutStarted, count: 180 },
        { stepIndex: 1, source: productViewed, target: null, count: 160 },
        { stepIndex: 1, source: checkoutStarted, target: productAdded, count: 120 },
        { stepIndex: 1, source: checkoutStarted, target: checkoutStarted, count: 250 },
        { stepIndex: 1, source: checkoutStarted, target: ordersView, count: 230 },
        { stepIndex: 1, source: checkoutStarted, target: null, count: 120 },
        { stepIndex: 1, source: pricingView, target: productAdded, count: 60 },
        { stepIndex: 1, source: pricingView, target: checkoutStarted, count: 130 },
        { stepIndex: 1, source: pricingView, target: ordersView, count: 105 },
        { stepIndex: 1, source: pricingView, target: null, count: 60 },
        { stepIndex: 1, source: null, target: ordersView, count: 70 },
        { stepIndex: 1, source: null, target: null, count: 110 },
        { stepIndex: 2, source: productAdded, target: purchaseCompleted, count: 560 },
        { stepIndex: 2, source: productAdded, target: productAdded, count: 180 },
        { stepIndex: 2, source: productAdded, target: null, count: 170 },
        { stepIndex: 2, source: checkoutStarted, target: purchaseCompleted, count: 300 },
        { stepIndex: 2, source: checkoutStarted, target: productAdded, count: 60 },
        { stepIndex: 2, source: checkoutStarted, target: null, count: 90 },
        { stepIndex: 2, source: ordersView, target: purchaseCompleted, count: 20 },
        { stepIndex: 2, source: ordersView, target: productAdded, count: 60 },
        { stepIndex: 2, source: ordersView, target: null, count: 80 },
        { stepIndex: 2, source: null, target: productAdded, count: 20 },
        { stepIndex: 2, source: null, target: null, count: 70 },
    ],
    prefixes: [
        { items: [signUp], count: 8240 },
        { items: [signUp, productViewed], count: 1350 },
        { items: [signUp, productViewed, productAdded], count: 520 },
        { items: [signUp, productViewed, productAdded, purchaseCompleted], count: 210 },
    ],
}

const meta: Meta<typeof JourneyGrid> = {
    title: 'Insights/Journeys/JourneyGrid',
    component: JourneyGrid,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
    },
}
export default meta

type Story = StoryObj<typeof JourneyGrid>

export const Anchored: Story = {
    render: () => (
        <JourneyGrid
            model={buildJourneyGridModel(MOCK_RESULTS)}
            isAnchored
            nodeColor="#1d4aff"
            onCardClick={() => {}}
            onRibbonClick={() => {}}
        />
    ),
}

export const AnchoredWithChainHighlight: Story = {
    render: () => {
        const chain = [signUp, productViewed, productAdded, purchaseCompleted]
        const counts = [8240, 1350, 520, 210]
        const totals = [8240, 5900, 3525, 1610]
        return (
            <JourneyGrid
                model={buildJourneyGridModel(MOCK_RESULTS)}
                isAnchored
                nodeColor="#1d4aff"
                chainHighlight={{
                    chain,
                    countByCardKey: Object.fromEntries(
                        chain.map((chainItem, position) => [chainCardKey(position, chainItem), counts[position]])
                    ),
                    fractionByCardKey: Object.fromEntries(
                        chain.map((chainItem, position) => [
                            chainCardKey(position, chainItem),
                            counts[position] / totals[position],
                        ])
                    ),
                    ribbonKeys: new Set(
                        chain
                            .slice(1)
                            .map((chainItem, position) =>
                                journeyRibbonKey(position, journeyItemKey(chain[position]), journeyItemKey(chainItem))
                            )
                    ),
                }}
                onCardClick={() => {}}
                onRibbonClick={() => {}}
            />
        )
    },
}
