import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { urls } from '~/scenes/urls'
import { initKeaTests } from '~/test/init'

import { BASE_POINT_LIMIT, ZOOMED_POINT_LIMIT, intentMapLogic } from './intentMapLogic'

jest.mock('lib/api')

const mockQuery = api.query as jest.Mock

const RESPONSE = {
    results: [
        {
            intent_hash: 'p1',
            intent_text: 'plot signups',
            x: 1,
            y: 0,
            topic_id: 'a',
            is_outlier: false,
            calls: 9,
            tool: 'query-trends',
        },
        {
            intent_hash: 'p2',
            intent_text: 'list flags',
            x: 0,
            y: 1,
            topic_id: 'b',
            is_outlier: false,
            calls: 7,
            tool: 'feature-flag-get-all',
        },
        {
            intent_hash: 'p3',
            intent_text: 'odd',
            x: 2,
            y: 2,
            topic_id: 'a',
            is_outlier: true,
            calls: 1,
            tool: 'query-trends',
        },
    ],
    topics: [
        { topic_id: 'a', label: 'Create insights', summary: 'Charts.', x: 1, y: 0, calls: 14, share_pct: 66.67 },
        { topic_id: 'b', label: 'List flags', summary: 'Flags.', x: 0, y: 1, calls: 7, share_pct: 33.33 },
    ],
    total_points: 3,
}

describe('intentMapLogic', () => {
    let logic: ReturnType<typeof intentMapLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockQuery.mockReset()
        mockQuery.mockResolvedValue(RESPONSE)
        logic = intentMapLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('reads tool, topic and dates from the url and loads the map once', async () => {
        logic.mount()
        router.actions.push(urls.mcpAnalyticsIntentMap({ tool: 'query-trends', topic: 'a' }) + '&date_from=-30d')

        await expectLogic(logic).toDispatchActions(['setTool', 'setTopicId', 'setDateFilter', 'loadMapSuccess'])

        expect(logic.values.tool).toBe('query-trends')
        expect(logic.values.topicId).toBe('a')
        expect(logic.values.dateFilter).toEqual({ dateFrom: '-30d', dateTo: null })
        expect(mockQuery).toHaveBeenCalledTimes(1)
        expect(mockQuery).toHaveBeenLastCalledWith(
            expect.objectContaining({
                kind: 'MCPIntentMapQuery',
                toolName: 'query-trends',
                topicId: 'a',
                dateRange: { date_from: '-30d', date_to: null },
                limit: BASE_POINT_LIMIT,
            })
        )
    })

    it('builds bubble and point series and resolves the selected topic', async () => {
        logic.mount()
        router.actions.push(urls.mcpAnalyticsIntentMap())
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

        expect(logic.values.topicSeries.map((s) => s.key)).toEqual(['topic-a', 'topic-b'])
        expect(logic.values.pointSeries.map((s) => [s.key, s.points.length])).toEqual([
            ['points-a', 1],
            ['points-b', 1],
            ['points-outliers', 1],
        ])
        expect(logic.values.totalPoints).toBe(3)

        logic.actions.selectTopic('a')
        expect(logic.values.selectedTopic?.label).toBe('Create insights')
        expect(logic.values.selectedTopicPoints.map((p) => p.intent_hash)).toEqual(['p1', 'p3'])
    })

    it('a drag zoom reloads the points inside the bounds with the larger limit', async () => {
        logic.mount()
        router.actions.push(urls.mcpAnalyticsIntentMap())
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

        logic.actions.setZoom({ x: [0.5, 1.5], y: [-0.5, 0.5] })
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

        expect(logic.values.isZoomed).toBe(true)
        expect(mockQuery).toHaveBeenLastCalledWith(
            expect.objectContaining({
                bounds: { x_min: 0.5, x_max: 1.5, y_min: -0.5, y_max: 0.5 },
                limit: ZOOMED_POINT_LIMIT,
            })
        )
    })

    it('narrowing to a topic clears the zoom, selects the topic and updates the url', async () => {
        logic.mount()
        router.actions.push(urls.mcpAnalyticsIntentMap())
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])
        logic.actions.setZoom({ x: [0, 1], y: [0, 1] })

        logic.actions.setTopicId('b')
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

        expect(logic.values.zoom).toBeNull()
        expect(logic.values.selectedTopicId).toBe('b')
        expect(router.values.searchParams).toEqual(expect.objectContaining({ topic: 'b' }))
        expect(mockQuery).toHaveBeenLastCalledWith(expect.objectContaining({ topicId: 'b', limit: BASE_POINT_LIMIT }))
        expect(mockQuery).toHaveBeenLastCalledWith(expect.not.objectContaining({ bounds: expect.anything() }))
    })
})
