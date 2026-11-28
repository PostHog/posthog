import type { Point } from '../../Workflows/hogflows/editor/tile-canvas/tileCanvasModel'
import type { AdventPollShares } from '../adventCalendarLogic'
import { ADVENT_LAST_DAY, ADVENT_QUESTION_DAYS, ADVENT_QUESTIONS } from '../adventContent'
import { drawAdventRewards } from '../adventDraw'
import { AdventProgress, buildAdventGraph } from '../adventGraph'
import { adventFlowLayout, AdventFlowLayout, AdventFlowOrientation, AdventFlowRect } from './adventFlowLayout'

const REWARDS = drawAdventRewards('0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01')
const ORIENTATIONS: AdventFlowOrientation[] = ['rows', 'column']
const DAYS = Array.from({ length: ADVENT_LAST_DAY }, (_, index) => index + 1)

function answered(days: number[]): Record<number, string> {
    return Object.fromEntries(
        ADVENT_QUESTION_DAYS.filter((day) => days.includes(day)).map((day) => [
            day,
            ADVENT_QUESTIONS[day].options[day % 2].id,
        ])
    )
}

const LEAF_REACH = 26
const ARROW_CLEARANCE = 10

const STATES = {
    'nothing open': { progress: { opened: [], answers: {} }, today: 1 },
    'the first week open': { progress: { opened: DAYS.slice(0, 6), answers: answered(DAYS.slice(0, 6)) }, today: 7 },
    'every door open': { progress: { opened: DAYS, answers: answered(DAYS) }, today: ADVENT_LAST_DAY },
} satisfies Record<string, { progress: AdventProgress; today: number }>

type State = keyof typeof STATES

function layoutOf(state: State, orientation: AdventFlowOrientation, shares: AdventPollShares = {}): AdventFlowLayout {
    const { progress, today } = STATES[state]
    return adventFlowLayout(buildAdventGraph(progress, today, REWARDS), shares, orientation)
}

const overlaps = (a: AdventFlowRect, b: AdventFlowRect): boolean =>
    a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height

const inside = (rect: AdventFlowRect, layout: AdventFlowLayout): boolean =>
    rect.x >= 0 && rect.y >= 0 && rect.x + rect.width <= layout.width && rect.y + rect.height <= layout.height

function crosses(from: Point, to: Point, rect: AdventFlowRect): boolean {
    const [left, right] = [Math.min(from.x, to.x), Math.max(from.x, to.x)]
    const [top, bottom] = [Math.min(from.y, to.y), Math.max(from.y, to.y)]
    return left < rect.x + rect.width && right > rect.x && top < rect.y + rect.height && bottom > rect.y
}

function onBorder(point: Point, rect: AdventFlowRect): boolean {
    const withinX = point.x >= rect.x && point.x <= rect.x + rect.width
    const withinY = point.y >= rect.y && point.y <= rect.y + rect.height
    const onSide = point.x === rect.x || point.x === rect.x + rect.width
    const onTopOrBottom = point.y === rect.y || point.y === rect.y + rect.height
    return (onSide && withinY) || (onTopOrBottom && withinX)
}

const between = (value: number, a: number, b: number): boolean => value >= Math.min(a, b) && value <= Math.max(a, b)

const onRun = (point: Point, [from, to]: [Point, Point]): boolean =>
    from.x === to.x
        ? point.x === from.x && between(point.y, from.y, to.y)
        : point.y === from.y && between(point.x, from.x, to.x)

const segments = (points: Point[]): [Point, Point][] => points.slice(1).map((point, index) => [points[index], point])

const cases: [AdventFlowOrientation, State][] = ORIENTATIONS.flatMap((orientation) =>
    (Object.keys(STATES) as State[]).map((state): [AdventFlowOrientation, State] => [orientation, state])
)

describe('adventFlowLayout', () => {
    it.each(ORIENTATIONS)('places the trigger, every door and the exit once in %s', (orientation) => {
        const { progress, today } = STATES['nothing open']
        const graph = buildAdventGraph(progress, today, REWARDS)

        const ids = adventFlowLayout(graph, {}, orientation).nodes.map((node) => node.id)

        expect(ids).toEqual(['trigger', ...graph.doors.map((door) => door.id), 'exit'])
    })

    it.each(cases)('keeps every tile and caption apart and on the canvas in %s with %s', (orientation, state) => {
        const layout = layoutOf(state, orientation)
        const footprints = layout.nodes.flatMap((node) => [
            { id: `${node.id} tile`, rect: node.tile },
            { id: `${node.id} caption`, rect: node.caption },
        ])

        const clashes = footprints.flatMap((a, index) =>
            footprints.slice(index + 1).flatMap((b) => (overlaps(a.rect, b.rect) ? [`${a.id} / ${b.id}`] : []))
        )
        const hovers = layout.nodes.flatMap((node) =>
            node.hover ? [{ id: `${node.id} hover`, rect: node.hover.rect }] : []
        )
        const outside = [...footprints, ...hovers]
            .filter((footprint) => !inside(footprint.rect, layout))
            .map(({ id }) => id)

        expect({ clashes, outside }).toEqual({ clashes: [], outside: [] })
    })

    it.each(cases)(
        'routes each edge from tile edge to tile edge, square, through no tile or caption, apart from the other arrows into its tile in %s with %s',
        (orientation, state) => {
            const layout = layoutOf(state, orientation)
            const byId = new Map(layout.nodes.map((node) => [node.id, node]))
            const footprints = layout.nodes.flatMap((node) => [node.tile, node.caption])

            const faults = layout.edges.flatMap((edge) => {
                const [source, target] = [byId.get(edge.source), byId.get(edge.target)]
                const runs = segments(edge.points)
                return [
                    !source || !onBorder(edge.points[0], source.tile) ? `${edge.id} leaves off its source` : null,
                    !target || !onBorder(edge.points[edge.points.length - 1], target.tile)
                        ? `${edge.id} lands off its target`
                        : null,
                    runs.some(([from, to]) => from.x !== to.x && from.y !== to.y) ? `${edge.id} runs diagonal` : null,
                    runs.some(([from, to]) => footprints.some((rect) => crosses(from, to, rect)))
                        ? `${edge.id} crosses a step`
                        : null,
                ].filter((fault): fault is string => fault !== null)
            })

            const unreached = layout.nodes
                .filter((node) => node.id !== 'trigger' && !layout.edges.some((edge) => edge.target === node.id))
                .map((node) => node.id)

            const crowded = layout.nodes.flatMap((node) => {
                const ends = layout.edges
                    .filter((edge) => edge.target === node.id)
                    .map((edge) => edge.points[edge.points.length - 1])
                const touch = ends.some((end, index) =>
                    ends
                        .slice(index + 1)
                        .some((other) => Math.hypot(end.x - other.x, end.y - other.y) < ARROW_CLEARANCE)
                )
                return touch ? [node.id] : []
            })

            expect({ faults, unreached, crowded }).toEqual({ faults: [], unreached: [], crowded: [] })
        }
    )

    it.each(cases)('draws an edge for every link of the graph in %s with %s', (orientation, state) => {
        const { progress, today } = STATES[state]
        const graph = buildAdventGraph(progress, today, REWARDS)

        const edgeIds = adventFlowLayout(graph, {}, orientation).edges.map((edge) => edge.id)

        expect(graph.links.map((link) => link.id).filter((id) => !edgeIds.includes(id))).toEqual([])
    })

    it.each(cases)('walks an edge once its source and its target door are open in %s with %s', (orientation, state) => {
        const layout = layoutOf(state, orientation)
        const isOpen = (id: string): boolean =>
            id === 'trigger' || layout.nodes.find((node) => node.id === id)?.door?.status === 'open'

        expect(layout.edges.map((edge) => [edge.id, edge.walked])).toEqual(
            layout.edges.map((edge) => [
                edge.id,
                isOpen(edge.source) && (edge.target === 'exit' || isOpen(edge.target)),
            ])
        )
    })

    it.each(ORIENTATIONS)('moves nothing when doors open and questions get answered in %s', (orientation) => {
        const before = layoutOf('nothing open', orientation)
        const after = layoutOf('every door open', orientation)
        const placeOf = new Map(before.nodes.map((node) => [node.id, { tile: node.tile, caption: node.caption }]))
        const routeOf = new Map(before.edges.map((edge) => [edge.id, edge.points]))

        expect(after.nodes.map((node) => [node.id, { tile: node.tile, caption: node.caption }])).toEqual(
            after.nodes.map((node) => [node.id, placeOf.get(node.id)])
        )
        expect(after.edges.map((edge) => [edge.id, edge.points])).toEqual(
            after.edges.map((edge) => [edge.id, routeOf.get(edge.id)])
        )
        expect([after.width, after.height]).toEqual([before.width, before.height])
    })

    it('puts the hover label of a desktop door on its right, or on its left at the right edge, clear of the leaf', () => {
        const layout = layoutOf('nothing open', 'rows')
        const sideOf = (id: string): string | undefined => layout.nodes.find((node) => node.id === id)?.hover?.side
        const besideTile = layout.nodes.every(
            ({ tile, hover }) =>
                !hover ||
                (hover.side === 'right'
                    ? hover.rect.x > tile.x + tile.width
                    : hover.rect.x + hover.rect.width <= tile.x - LEAF_REACH)
        )

        expect([sideOf('door-1'), sideOf('door-8'), sideOf('trigger')]).toEqual(['right', 'left', undefined])
        expect(besideTile).toBe(true)
        expect(layoutOf('nothing open', 'column').nodes.filter((node) => node.hover)).toEqual([])
    })

    it.each(ORIENTATIONS)(
        'labels each branch with its option and share on the run into its lane in %s',
        (orientation) => {
            const layout = adventFlowLayout(buildAdventGraph({ opened: [1], answers: {} }, 2, REWARDS), {}, orientation)
            const answered = adventFlowLayout(
                buildAdventGraph({ opened: [1, 2], answers: { 2: 'tim' } }, 3, REWARDS),
                { 2: { james: 38, tim: 62 } },
                orientation
            )
            const tileOf = (id: string): AdventFlowRect | undefined => layout.nodes.find((node) => node.id === id)?.tile

            const branches = layout.edges.filter((edge) => edge.source === 'door-2')
            const lastRunHolds = branches.map((edge) => {
                const [from, to] = edge.points.slice(-2)
                return !!edge.labelAt && onRun(edge.labelAt, [from, to])
            })

            expect(branches.map((edge) => [edge.target, edge.label, edge.share])).toEqual([
                ['door-3-upper', 'James', null],
                ['door-3-lower', 'Tim', null],
            ])
            expect(
                answered.edges
                    .filter((edge) => edge.source === 'door-2')
                    .map((edge) => [edge.target, edge.label, edge.share])
            ).toEqual([['door-3-lower', 'Tim', 62]])
            expect(lastRunHolds).toEqual([true, true])
            const [upper, lower] = [tileOf('door-3-upper'), tileOf('door-3-lower')]
            expect(upper && lower && (orientation === 'rows' ? upper.y < lower.y : upper.x < lower.x)).toBe(true)
        }
    )
})
