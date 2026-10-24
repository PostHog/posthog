import type { FlameNode } from '@posthog/quill-charts'

import { CompareLabelType } from '~/types'

import { buildBreakdownIcicle, type BreakdownIcicleResult } from './trendsBreakdownIcicleTransforms'

const row = (overrides: Partial<BreakdownIcicleResult>): BreakdownIcicleResult => ({
    action: null,
    label: '$pageview',
    order: 0,
    aggregated_value: 0,
    ...overrides,
})

const OPTIONS = {
    rootLabel: 'Pageview',
    seriesLabel: (r: BreakdownIcicleResult) => (r.order === 0 ? 'Pageview' : 'Sign up'),
    formatValue: (value: string | number, level: number) => `${value}@${level}`,
}

/** name:value, with children in brackets, so a whole tree reads as one string. */
function shape(node: FlameNode): string {
    const children = node.children?.map(shape).join(', ')
    return `${node.name}:${node.value}${children ? ` [${children}]` : ''}`
}

describe('buildBreakdownIcicle', () => {
    it('nests each breakdown inside the one before it and sums parents from their children', () => {
        const tree = buildBreakdownIcicle(
            [
                row({ breakdown_value: ['US', 'Chrome'], aggregated_value: 60 }),
                row({ breakdown_value: ['US', 'Safari'], aggregated_value: 30 }),
                row({ breakdown_value: ['DE', 'Chrome'], aggregated_value: 10 }),
            ],
            OPTIONS
        )
        expect(shape(tree)).toBe('Pageview:100 [US@0:90 [Chrome@1:60, Safari@1:30], DE@0:10 [Chrome@1:10]]')
        expect(tree.children?.[0].children?.[1]).toMatchObject({
            group: 'US@0',
            meta: { breakdownValues: ['US', 'Safari'] },
        })
    })

    it('adds a series level when the insight has several series', () => {
        const tree = buildBreakdownIcicle(
            [
                row({ order: 0, breakdown_value: 'US', aggregated_value: 5 }),
                row({ order: 1, breakdown_value: 'US', aggregated_value: 2 }),
            ],
            { ...OPTIONS, rootLabel: 'All series' }
        )
        expect(shape(tree)).toBe('All series:7 [Pageview:5 [US@0:5], Sign up:2 [US@0:2]]')
    })

    it('skips previous-period rows and rows without a positive total', () => {
        const tree = buildBreakdownIcicle(
            [
                row({ breakdown_value: ['US'], aggregated_value: 4 }),
                row({ breakdown_value: ['US'], aggregated_value: 40, compare_label: CompareLabelType.Previous }),
                row({ breakdown_value: ['FR'], aggregated_value: 0 }),
                row({ breakdown_value: ['DE'], aggregated_value: Number.NaN }),
            ],
            OPTIONS
        )
        expect(shape(tree)).toBe('Pageview:4 [US@0:4]')
    })
})
