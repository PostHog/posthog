import { NodeKind } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { buildLaunchReview, notebookFunnel } from './launchReview'
import { appSourceCells, emptyAppLayout, newAppBlock } from './notebookAppLayout'

it('keeps the existing app and binds the review, funnel population, and playlist to the selected flag value', () => {
    const layout = emptyAppLayout()
    layout.blocks.push(newAppBlock('text', 'overview', { text: 'Prior analysis' }))
    const result = buildLaunchReview('<FeatureFlag id={42} />', layout, {
        flagId: 42,
        flagKey: 'example-checkout',
        flagValue: 'compact',
        funnel: {
            kind: NodeKind.FunnelsQuery,
            dateRange: { date_from: '-14d' },
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: 'checkout opened',
                    properties: [
                        {
                            type: PropertyFilterType.Event,
                            key: 'platform',
                            operator: PropertyOperator.Exact,
                            value: ['web'],
                        },
                    ],
                },
                { kind: NodeKind.EventsNode, event: 'checkout completed' },
            ],
        },
    })
    const cells = appSourceCells(result.markdown)
    expect(cells).toHaveLength(3)
    expect(result.layout.tabs[1].id).toBe(result.tabId)
    expect(result.layout.blocks[0]).toEqual(layout.blocks[0])
    expect(result.layout.blocks.slice(1).map((block) => block.node_id)).toEqual(cells.map((cell) => cell.id))
    expect(cells[0]).toMatchObject({ tagName: 'FeatureFlag', props: { id: 42 } })
    const flagProperty = { key: '$feature/example-checkout', operator: 'exact', type: 'event', value: ['compact'] }
    expect(notebookFunnel(cells[1])).toMatchObject({
        dateRange: { date_from: '-14d' },
        series: [
            { event: 'checkout opened', properties: [expect.objectContaining({ key: 'platform' }), flagProperty] },
            { event: 'checkout completed' },
        ],
    })
    expect(cells[2]).toMatchObject({
        tagName: 'RecordingPlaylist',
        props: {
            universalFilters: {
                date_from: '-14d',
                filter_group: {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [flagProperty] }],
                },
            },
        },
    })
})
