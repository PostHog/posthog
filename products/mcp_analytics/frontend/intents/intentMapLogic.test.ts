import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { urls } from '~/scenes/urls'
import { initKeaTests } from '~/test/init'

import { BASE_POINT_LIMIT, TOPIC_POINTS_PAGE_SIZE, ZOOMED_POINT_LIMIT, intentMapLogic } from './intentMapLogic'

jest.mock('lib/api')
// jsdom has no theme CSS, so every real palette color resolves to the same fallback.
jest.mock('lib/colors', () => ({
    ...jest.requireActual('lib/colors'),
    getSeriesColor: (index: number) => `series-${index}`,
}))

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
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MCP_ANALYTICS_INTENT_TOPICS], {
            [FEATURE_FLAGS.MCP_ANALYTICS_INTENT_TOPICS]: true,
        })
        logic = intentMapLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        { dateFrom: '-30d', dateTo: '-1d', expectedFilter: { dateFrom: '-30d', dateTo: '-1d' } },
        { dateFrom: null, dateTo: null, expectedFilter: { dateFrom: '-7d', dateTo: null } },
    ])(
        'reads tool, topic and dates ($dateFrom, $dateTo) from the url, loads the map once and adds no history entry',
        async ({ dateFrom, dateTo, expectedFilter }) => {
            logic.mount()
            const pushSpy = jest.spyOn(router.actions, 'push')
            const replaceSpy = jest.spyOn(router.actions, 'replace')
            const entryUrl = urls.mcpAnalyticsIntentMap({ tool: 'query-trends', topic: 'a', dateFrom, dateTo })
            router.actions.push(entryUrl)

            await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

            expect(logic.values.tool).toBe('query-trends')
            expect(logic.values.topicId).toBe('a')
            expect(logic.values.dateFilter).toEqual(expectedFilter)
            expect(mockQuery).toHaveBeenCalledTimes(1)
            expect(mockQuery).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    kind: 'MCPIntentMapQuery',
                    toolName: 'query-trends',
                    topicId: 'a',
                    dateRange: { date_from: expectedFilter.dateFrom, date_to: expectedFilter.dateTo },
                    limit: BASE_POINT_LIMIT,
                })
            )
            expect(pushSpy).toHaveBeenCalledTimes(1)
            expect(replaceSpy).not.toHaveBeenCalled()
            expect(router.values.location.search).toBe(entryUrl.slice(entryUrl.indexOf('?')))
        }
    )

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

    it('a bubble click narrows the map to the topic and records the selection once', async () => {
        logic.mount()
        router.actions.push(urls.mcpAnalyticsIntentMap())
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])
        jest.mocked(posthog.capture).mockClear()

        logic.actions.focusTopic('b')
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

        expect(logic.values.topicId).toBe('b')
        expect(logic.values.selectedTopicId).toBe('b')
        expect(router.values.searchParams).toEqual(expect.objectContaining({ topic: 'b' }))
        expect(
            jest.mocked(posthog.capture).mock.calls.filter(([event]) => event === 'mcp analytics intent topic selected')
        ).toEqual([['mcp analytics intent topic selected', { topic_id: 'b' }]])
    })

    it('keeps each topic color when the map narrows to one topic', async () => {
        logic.mount()
        router.actions.push(urls.mcpAnalyticsIntentMap())
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])
        const colorOfB = logic.values.topicSeries.find((s) => s.key === 'topic-b')?.color

        mockQuery.mockResolvedValue({
            ...RESPONSE,
            results: RESPONSE.results.filter((p) => p.topic_id === 'b'),
            topics: RESPONSE.topics.filter((t) => t.topic_id === 'b'),
        })
        logic.actions.setTopicId('b')
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

        expect(colorOfB).toBe('series-1')
        expect(logic.values.topicSeries.find((s) => s.key === 'topic-b')?.color).toBe(colorOfB)
        expect(logic.values.pointSeries.find((s) => s.key === 'points-b')?.color).toBe(colorOfB)
        expect(logic.values.topicColor('b')).toBe(colorOfB)
    })

    it('sends no query while the intent topics flag is off, and loads once it turns on', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        logic.mount()
        router.actions.push(urls.mcpAnalyticsIntentMap())

        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

        expect(mockQuery).not.toHaveBeenCalled()
        expect(logic.values.points).toEqual([])

        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MCP_ANALYTICS_INTENT_TOPICS], {
            [FEATURE_FLAGS.MCP_ANALYTICS_INTENT_TOPICS]: true,
        })
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

        expect(mockQuery).toHaveBeenCalledTimes(1)
        expect(logic.values.points.map((p) => p.intent_hash)).toEqual(['p1', 'p2', 'p3'])
    })

    it('keeps a failed load apart from an empty map until a load succeeds', async () => {
        mockQuery.mockRejectedValueOnce(new Error('timeout'))
        logic.mount()
        router.actions.push(urls.mcpAnalyticsIntentMap())
        await expectLogic(logic).toDispatchActions(['loadMapFailure'])

        expect(logic.values.mapError).toBeTruthy()

        logic.actions.loadMap()
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

        expect(logic.values.mapError).toBeNull()
    })

    it('shows the selected topic intents one page at a time', async () => {
        const many = Array.from({ length: TOPIC_POINTS_PAGE_SIZE * 2 + 5 }, (_, i) => ({
            ...RESPONSE.results[0],
            intent_hash: `h${i}`,
            calls: 1000 - i,
        }))
        mockQuery.mockResolvedValue({ ...RESPONSE, results: many })
        logic.mount()
        router.actions.push(urls.mcpAnalyticsIntentMap())
        await expectLogic(logic).toDispatchActions(['loadMapSuccess'])

        logic.actions.selectTopic('a')
        expect(logic.values.visibleTopicPoints.map((p) => p.intent_hash)).toEqual(
            many.slice(0, TOPIC_POINTS_PAGE_SIZE).map((p) => p.intent_hash)
        )

        logic.actions.showMoreTopicPoints()
        logic.actions.showMoreTopicPoints()
        expect(logic.values.visibleTopicPoints).toHaveLength(many.length)

        logic.actions.selectTopic('b')
        logic.actions.selectTopic('a')
        expect(logic.values.visibleTopicPoints).toHaveLength(TOPIC_POINTS_PAGE_SIZE)
    })
})
