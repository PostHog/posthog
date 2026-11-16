import { Meta, StoryObj } from '@storybook/react'

import { SPAN_TREE_CURRENT, SPAN_TREE_PREVIOUS } from './__mocks__/spanTreeCompare'
import { TraceCompareFlame } from './TraceCompareFlame'
import { buildTree } from './traceFlameTree'

const meta: Meta<typeof TraceCompareFlame> = {
    title: 'Products/Tracing/TraceCompareFlame',
    component: TraceCompareFlame,
    args: {
        current: SPAN_TREE_CURRENT,
        previous: SPAN_TREE_PREVIOUS,
        loading: false,
        initialSpanName: null,
        surface: 'compare_modal',
    },
    decorators: [
        (Story) => (
            <div className="w-[1100px] p-4">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof TraceCompareFlame>

export const Default: Story = {}

export const FocusedOnSpan: Story = {
    args: { initialSpanName: 'payments.charge' },
}

export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[400px]">
                <Story />
            </div>
        ),
    ],
}

export const NoBaseline: Story = {
    args: { previous: null },
}

export const SingleTrace: Story = {
    args: {
        tree: buildTree(SPAN_TREE_CURRENT, null),
        previous: null,
        sizeBy: 'total',
        serviceColorMap: new Map(
            Array.from(new Set(SPAN_TREE_CURRENT.map((row) => row.service_name)), (service, index) => [service, index])
        ),
        surface: 'drawer',
    },
}

export const Empty: Story = {
    args: { current: [], previous: [] },
}
