import { expectLogic } from 'kea-test-utils'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { teamLogic } from 'scenes/teamLogic'

import { examples } from '~/queries/examples'
import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, PathType, PropertyFilterType, PropertyOperator } from '~/types'

import {
    buildFunnelEventsFromPathNode,
    pathsDataLogic,
} from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'

import { PathNodeData, PathTargetLink } from './pathUtils'

let logic: ReturnType<typeof pathsDataLogic.build>

const insightProps: InsightLogicProps = {
    dashboardItemId: undefined,
    cachedInsight: {
        query: { kind: NodeKind.InsightVizNode, source: examples.InsightPathsQuery } as InsightVizNode,
    },
}

async function initPathsDataLogic(): Promise<void> {
    logic = pathsDataLogic(insightProps)
    logic.mount()
    await expectLogic(logic).toFinishAllListeners()
}

describe('pathsDataLogic', () => {
    beforeEach(async () => {
        initKeaTests(false)
        teamLogic.mount()
        await initPathsDataLogic()
    })

    it('selects taxonomicGroupTypes from pathsFilter', async () => {
        await expectLogic(logic, () => {
            logic.actions.updateInsightFilter({
                includeEventTypes: [PathType.PageView, PathType.Screen, PathType.CustomEvent],
            })
        })
            .toFinishAllListeners()
            .toMatchValues(logic, {
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.PageviewUrls,
                    TaxonomicFilterGroupType.Screens,
                    TaxonomicFilterGroupType.CustomEvents,
                    TaxonomicFilterGroupType.Wildcards,
                ],
            })
    })
})

const makeNode = (name: string, depth: number, parent?: PathNodeData): PathNodeData =>
    ({
        name,
        depth,
        targetLinks: parent ? [{ source: parent } as PathTargetLink] : [],
    }) as PathNodeData

describe('buildFunnelEventsFromPathNode', () => {
    it.each([
        {
            scenario: 'custom event',
            node: makeNode('1_signed_up', 0),
            expected: [{ kind: NodeKind.EventsNode, event: 'signed_up', name: 'signed_up' }],
        },
        {
            scenario: 'URL node adds $pageview with $current_url property',
            node: makeNode('1_https://example.com/page', 0),
            expected: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    properties: [
                        {
                            key: '$current_url',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: 'https://example.com/page',
                        },
                    ],
                },
            ],
        },
        {
            scenario: 'relative path',
            node: makeNode('1_/dashboard', 0),
            expected: [{ kind: NodeKind.EventsNode, event: '/dashboard', name: '/dashboard' }],
        },
        {
            scenario: 'screen name',
            node: makeNode('1_$screen', 0),
            expected: [{ kind: NodeKind.EventsNode, event: '$screen', name: '$screen' }],
        },
        {
            scenario: 'chain of mixed nodes comes back in funnel step order',
            node: (() => {
                const start = makeNode('1_https://example.com/', 0)
                return makeNode('2_signed_up', 1, start)
            })(),
            expected: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    properties: [
                        {
                            key: '$current_url',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                            value: 'https://example.com/',
                        },
                    ],
                },
                { kind: NodeKind.EventsNode, event: 'signed_up', name: 'signed_up' },
            ],
        },
    ])('$scenario', ({ node, expected }) => {
        expect(buildFunnelEventsFromPathNode(node)).toEqual(expected)
    })
})
