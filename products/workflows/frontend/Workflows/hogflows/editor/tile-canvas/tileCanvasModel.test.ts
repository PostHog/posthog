import type { HogFlow, HogFlowAction, HogFlowEdge } from '../../types'
import {
    computePathGroups,
    computeVisibleGraph,
    countableStepMetrics,
    filterPaletteItems,
    isHeadingToRect,
    layoutMiniFlow,
    PaletteCommand,
    PaletteSection,
    PathPlace,
    stepCount,
    stepCountsRequest,
    viewportAfterResize,
    readableFitViewport,
    viewportAnchoredOn,
    viewportToFit,
} from './tileCanvasModel'

const step = (id: string, type: HogFlowAction['type'] = 'function'): HogFlowAction =>
    ({ id, type, name: id, description: '', config: {} }) as HogFlowAction

const next = (from: string, to: string): HogFlowEdge => ({ from, to, type: 'continue' })
const branch = (from: string, to: string, index = 0): HogFlowEdge => ({ from, to, type: 'branch', index })

const flow = (actions: HogFlowAction[], edges: HogFlowEdge[]): Pick<HogFlow, 'actions' | 'edges'> => ({
    actions,
    edges,
})

// trigger -> split, whose branch path holds two steps and whose other path holds one, both joining at exit
const splitWithLongAndShortPath = (splitType: HogFlowAction['type']): Pick<HogFlow, 'actions' | 'edges'> =>
    flow(
        [
            step('trigger', 'trigger'),
            step('split', splitType),
            step('a1'),
            step('a2'),
            step('b1'),
            step('exit', 'exit'),
        ],
        [
            next('trigger', 'split'),
            branch('split', 'a1'),
            next('a1', 'a2'),
            next('a2', 'exit'),
            next('split', 'b1'),
            next('b1', 'exit'),
        ]
    )

// The outer split's branch path holds an inner split with two paths of two steps each
const nestedSplits = flow(
    [
        step('trigger', 'trigger'),
        step('outer', 'conditional_branch'),
        step('inner', 'conditional_branch'),
        step('x1'),
        step('x2'),
        step('y1'),
        step('y2'),
        step('other'),
        step('exit', 'exit'),
    ],
    [
        next('trigger', 'outer'),
        branch('outer', 'inner'),
        branch('inner', 'x1'),
        next('x1', 'x2'),
        next('x2', 'exit'),
        next('inner', 'y1'),
        next('y1', 'y2'),
        next('y2', 'exit'),
        next('outer', 'other'),
        next('other', 'exit'),
    ]
)

describe('tileCanvasModel', () => {
    it.each(['conditional_branch', 'random_cohort_branch', 'wait_until_condition'] as const)(
        'groups a %s path only when it holds two or more steps',
        (splitType) => {
            const groups = computePathGroups(splitWithLongAndShortPath(splitType))

            expect(groups.map((group) => ({ branch: group.branchActionId, members: group.memberIds }))).toEqual([
                { branch: 'split', members: ['a1', 'a2'] },
            ])
        }
    )

    it('gives a nested path its enclosing path as parent', () => {
        const groups = computePathGroups(nestedSplits)
        const outer = groups.find((group) => group.branchActionId === 'outer')
        const inner = groups.filter((group) => group.branchActionId === 'inner')

        expect(outer?.memberIds).toEqual(expect.arrayContaining(['inner', 'x1', 'x2', 'y1', 'y2']))
        expect(inner.map((group) => [group.memberIds, group.parentId, group.depth])).toEqual([
            [['x1', 'x2'], outer?.id, 1],
            [['y1', 'y2'], outer?.id, 1],
        ])
    })

    it.each([
        {
            name: 'steps stored out of flow order',
            workflow: flow(
                [
                    step('exit', 'exit'),
                    step('a2'),
                    step('b1'),
                    step('a1'),
                    step('split', 'conditional_branch'),
                    step('trigger', 'trigger'),
                ],
                splitWithLongAndShortPath('conditional_branch').edges
            ),
            splitId: 'split',
            members: ['a1', 'a2'],
        },
        {
            name: 'a step inserted before the first step of the path',
            workflow: flow(
                [...splitWithLongAndShortPath('conditional_branch').actions, step('first')],
                [
                    next('trigger', 'split'),
                    branch('split', 'first'),
                    next('first', 'a1'),
                    next('a1', 'a2'),
                    next('a2', 'exit'),
                    next('split', 'b1'),
                    next('b1', 'exit'),
                ]
            ),
            splitId: 'split',
            members: ['first', 'a1', 'a2'],
        },
        {
            name: 'a nested split, one inner path after the other',
            workflow: flow([...nestedSplits.actions].reverse(), nestedSplits.edges),
            splitId: 'outer',
            members: ['inner', 'x1', 'x2', 'y1', 'y2'],
        },
    ])('orders a path the way people move through it: $name', ({ workflow, splitId, members }) => {
        const group = computePathGroups(workflow).find((candidate) => candidate.branchActionId === splitId)

        expect(group?.memberIds).toEqual(members)
    })

    it('lists the visible steps in flow order, whatever order they are stored in', () => {
        const workflow = flow([...nestedSplits.actions].reverse(), nestedSplits.edges)

        const graph = computeVisibleGraph(workflow, [], [])

        expect(graph.nodes.map((node) => node.id)).toEqual([
            'trigger',
            'outer',
            'inner',
            'x1',
            'x2',
            'y1',
            'y2',
            'other',
            'exit',
        ])
    })

    it('folds the paths of a split inside a retry loop, while the retry path itself stays open', () => {
        const retry = flow(
            [
                step('trigger', 'trigger'),
                step('start'),
                step('split', 'conditional_branch'),
                step('a1'),
                step('a2'),
                step('b1'),
                step('b2'),
                step('check', 'conditional_branch'),
                step('exit', 'exit'),
            ],
            [
                next('trigger', 'start'),
                next('start', 'split'),
                branch('split', 'a1'),
                next('a1', 'a2'),
                next('a2', 'check'),
                next('split', 'b1'),
                next('b1', 'b2'),
                next('b2', 'check'),
                branch('check', 'start'),
                next('check', 'exit'),
            ]
        )

        expect(computePathGroups(retry).map((group) => group.memberIds)).toEqual([
            ['a1', 'a2'],
            ['b1', 'b2'],
        ])
    })

    it('leaves paths that loop back into each other ungrouped', () => {
        const loop = flow(
            [
                step('trigger', 'trigger'),
                step('s', 'conditional_branch'),
                step('a'),
                step('t', 'conditional_branch'),
                step('b'),
                step('exit', 'exit'),
            ],
            [
                next('trigger', 's'),
                branch('s', 'a'),
                next('a', 't'),
                next('s', 'exit'),
                branch('t', 'b'),
                next('b', 's'),
                next('t', 'exit'),
            ]
        )

        const groups = computePathGroups(loop)

        expect(groups).toEqual([])
        expect(computeVisibleGraph(loop, groups, []).nodes.map((node) => node.id)).toEqual([
            'trigger',
            's',
            'a',
            't',
            'b',
            'exit',
        ])
    })

    it('draws a collapsed path as one stack that takes over its arrows', () => {
        const workflow = splitWithLongAndShortPath('conditional_branch')
        const [group] = computePathGroups(workflow)

        const graph = computeVisibleGraph(workflow, [group], [])

        expect(graph.nodes.map((node) => node.id)).toEqual(['trigger', 'split', group.id, 'b1', 'exit'])
        expect(graph.edges.map((edge) => [edge.source, edge.target])).toEqual(
            expect.arrayContaining([
                ['split', group.id],
                [group.id, 'exit'],
            ])
        )
    })

    it('hides the paths inside a collapsed path, and shows the steps of an open one', () => {
        const groups = computePathGroups(nestedSplits)
        const outer = groups.find((group) => group.branchActionId === 'outer')!
        const inner = groups.filter((group) => group.branchActionId === 'inner')

        const outerCollapsed = computeVisibleGraph(nestedSplits, groups, [])
        expect(outerCollapsed.nodes.filter((node) => node.kind === 'stack').map((node) => node.id)).toEqual([outer.id])

        const outerOpen = computeVisibleGraph(nestedSplits, groups, [outer.id])
        expect(outerOpen.nodes.map((node) => node.id)).toEqual(
            expect.arrayContaining(['inner', inner[0].id, inner[1].id])
        )
        expect(outerOpen.nodes.map((node) => node.id)).not.toContain('x1')
    })

    it('lays a path out left to right, stacking a fork in one column around its split', () => {
        const workflow = flow(
            [step('split', 'conditional_branch'), step('yes'), step('no'), step('after')],
            [branch('split', 'yes'), next('split', 'no'), next('yes', 'after')]
        )

        const layout = layoutMiniFlow(workflow, ['split', 'yes', 'no', 'after'], { tile: 32, gapX: 30, gapY: 50 })
        const at = Object.fromEntries(layout.nodes.map((node) => [node.actionId, { x: node.x, y: node.y }]))

        expect(at).toEqual({
            split: { x: 0, y: 25 },
            yes: { x: 62, y: 0 },
            no: { x: 62, y: 50 },
            after: { x: 124, y: 25 },
        })
        expect(layout.edges).toHaveLength(3)
        expect(layout.width).toBe(156)
    })

    it.each([
        ['straight toward the preview', { x: 100, y: 150 }, true],
        ['sideways away from the preview', { x: 10, y: 110 }, false],
        ['past the side of the preview', { x: 400, y: 190 }, false],
    ])('keeps the open preview while the pointer moves %s', (_, pointer, expected) => {
        const apex = { x: 100, y: 100 }
        const preview = { left: 40, right: 260, top: 200 }

        expect(isHeadingToRect(pointer, apex, preview, 12)).toBe(expected)
    })

    it.each([
        ['an empty search lists commands first', '', ['Fit to screen', 'Email', 'Delay']],
        ['a search matches step descriptions and section names', 'wait', ['Delay']],
        ['a search matches commands too', 'screen', ['Fit to screen']],
        ['a search with no match lists nothing', 'zebra', []],
    ])('filters the palette: %s', (_, query, expected) => {
        const sections: PaletteSection[] = [
            {
                title: 'Send',
                steps: [
                    {
                        type: 'function_email',
                        name: 'Email',
                        description: 'Send an email.',
                        config: { template_id: 'template-email', inputs: {} },
                    },
                ],
            },
            {
                title: 'Wait',
                steps: [{ type: 'delay', name: 'Delay', description: 'Pause.', config: { delay_duration: '1h' } }],
            },
        ]
        const commands: PaletteCommand[] = [{ id: 'fit', label: 'Fit to screen', hint: 'Show every step' }]

        expect(filterPaletteItems(query, sections, commands).map((item) => item.label)).toEqual(expected)
    })

    it('keeps two destinations that share a name apart in the palette', () => {
        const destination = (templateId: string): PaletteSection['steps'][number] => ({
            type: 'function',
            name: 'Hubspot',
            description: '',
            config: { template_id: templateId, inputs: {} },
        })
        const sections = [
            { title: 'More destinations', steps: [destination('hubspot'), destination('hubspot-contacts')] },
        ]

        const keys = filterPaletteItems('', sections, []).map((item) => item.key)

        expect(new Set(keys).size).toBe(2)
    })

    it('counts every person a step handled once metrics load', () => {
        const metrics = { email: { actionId: 'email', succeeded: 40, failed: 2, filtered: 8 } }

        expect(stepCount(metrics, 'email')).toBe(50)
        expect(stepCount(metrics, 'delay')).toBe(0)
        expect(stepCount(null, 'email')).toBeUndefined()
        expect(stepCount({}, 'email')).toBeUndefined()
    })

    it.each([
        {
            name: 'keeps the middle of the view when the panel opens',
            startX: 100,
            previousWidth: 1200,
            nextWidth: 600,
            focus: undefined,
            expected: { x: -200, y: 50, zoom: 0.5 },
        },
        {
            name: 'gives the view back when the panel closes',
            startX: -200,
            previousWidth: 600,
            nextWidth: 1200,
            focus: undefined,
            expected: { x: 100, y: 50, zoom: 0.5 },
        },
        {
            name: 'leaves a selected step that is still in view alone',
            startX: 100,
            previousWidth: 1200,
            nextWidth: 600,
            focus: { x: 1000, y: 0, width: 64, height: 64 },
            expected: { x: -200, y: 50, zoom: 0.5 },
        },
        {
            name: 'pulls a selected step back in from the right edge',
            startX: 100,
            previousWidth: 1200,
            nextWidth: 600,
            focus: { x: 1600, y: 0, width: 64, height: 64 },
            expected: { x: -256, y: 50, zoom: 0.5 },
        },
        {
            name: 'pulls a selected step back in from the left edge',
            startX: 100,
            previousWidth: 1200,
            nextWidth: 600,
            focus: { x: 0, y: 0, width: 64, height: 64 },
            expected: { x: 24, y: 50, zoom: 0.5 },
        },
        {
            name: 'lifts a selected step out from under the command bar',
            startX: 100,
            previousWidth: 1200,
            nextWidth: 1200,
            focus: { x: 0, y: 1400, width: 64, height: 64 },
            expected: { x: 100, y: -28, zoom: 0.5 },
        },
    ])('moves the viewport on a canvas resize: $name', ({ startX, previousWidth, nextWidth, focus, expected }) => {
        const viewport = { x: startX, y: 50, zoom: 0.5 }

        expect(
            viewportAfterResize(
                viewport,
                { width: previousWidth, height: 800 },
                { width: nextWidth, height: 800 },
                focus
            )
        ).toEqual(expected)
    })
})

describe('viewportToFit', () => {
    const canvas = { width: 1000, height: 700 }

    it.each([
        {
            name: 'centres a frame that already fits, at the zoom the person chose',
            frame: { x: 100, y: 200, width: 400, height: 300 },
            zoom: 0.8,
            expected: { x: 260, y: 32 + (572 - 240) / 2 - 200 * 0.8, zoom: 0.8 },
        },
        {
            name: 'zooms out until a wide frame fits, then centres it',
            frame: { x: 0, y: 0, width: 1904, height: 300 },
            zoom: 1,
            expected: { x: 24, y: 32 + (572 - 150) / 2, zoom: 0.5 },
        },
        {
            name: 'never zooms out further than the canvas allows',
            frame: { x: 0, y: 0, width: 20000, height: 300 },
            zoom: 1,
            expected: { x: 500 - 10000 * 0.15, y: 32 + (572 - 45) / 2, zoom: 0.15 },
        },
    ])('$name', ({ frame, zoom, expected }) => {
        const viewport = viewportToFit(frame, canvas, zoom)

        expect(viewport.zoom).toBeCloseTo(expected.zoom)
        expect(viewport.x).toBeCloseTo(expected.x)
        expect(viewport.y).toBeCloseTo(expected.y)
    })
})

describe('viewportAnchoredOn', () => {
    const canvas = { width: 1000, height: 700 }
    const place = (x: number, y: number, width: number, height: number, entryX = x + width / 2): PathPlace => ({
        x,
        y,
        width,
        height,
        entry: { x: entryX, y },
    })
    const stack = place(400, 600, 180, 90, 430)
    const entryOnScreen = (
        of: PathPlace,
        viewport: { x: number; y: number; zoom: number }
    ): { x: number; y: number } => ({
        x: viewport.x + of.entry.x * viewport.zoom,
        y: viewport.y + of.entry.y * viewport.zoom,
    })

    it.each([
        {
            name: 'opens a path where the arrow met its stack, at the same zoom',
            next: place(300, 620, 520, 300),
            zoom: 1,
        },
        {
            name: 'collapses a path into a stack where the arrow met its frame, even zoomed far out',
            next: place(380, 1400, 180, 90, 410),
            zoom: 0.2,
        },
    ])('$name', ({ next, zoom }) => {
        const viewport = { x: 500 - 430 * zoom, y: 150 - 600 * zoom, zoom }

        const anchored = viewportAnchoredOn(stack, next, viewport, canvas)

        expect(anchored.zoom).toBe(zoom)
        expect(entryOnScreen(next, anchored)).toEqual(entryOnScreen(stack, viewport))
    })

    it.each([
        { name: 'zooms out just enough to show a tall frame from where its stack was', height: 692.5, zoom: 0.8 },
        { name: 'stops zooming out at a readable zoom', height: 5000, zoom: 0.66 },
    ])('$name', ({ height, zoom }) => {
        const viewport = { x: 500 - 430, y: 50 - 600, zoom: 1 }
        const frame = place(300, 620, 520, height)

        const anchored = viewportAnchoredOn(stack, frame, viewport, canvas)

        expect(anchored.zoom).toBeCloseTo(zoom)
        expect(entryOnScreen(frame, anchored)).toEqual(entryOnScreen(stack, viewport))
    })

    it('keeps a zoom the person set below the readable one', () => {
        const anchored = viewportAnchoredOn(stack, place(300, 620, 520, 5000), { x: 0, y: 0, zoom: 0.3 }, canvas)

        expect(anchored.zoom).toBe(0.3)
    })

    it('slides a frame sideways into view when it would open past the edge of the canvas', () => {
        const frame = place(300, 620, 520, 300, 750)

        const anchored = viewportAnchoredOn(stack, frame, { x: 100 - 430, y: 150 - 600, zoom: 1 }, canvas)

        expect(anchored.zoom).toBe(1)
        expect({ left: anchored.x + frame.x, top: anchored.y + frame.y }).toEqual({ left: 24, top: 150 })
    })

    it('brings a stack into view when the frame it replaces started above the canvas', () => {
        const frame = place(300, 0, 520, 3000)
        const next = place(470, 0, 180, 90)

        const anchored = viewportAnchoredOn(frame, next, { x: 0, y: -1000, zoom: 1 }, canvas)

        expect(entryOnScreen(next, anchored)).toEqual({ x: 560, y: 32 })
    })

    it('centres a path that opens from a stack out of view', () => {
        const frame = place(300, 620, 520, 300)

        expect(viewportAnchoredOn(stack, frame, { x: 0, y: -5000, zoom: 1 }, canvas)).toEqual(
            viewportToFit(frame, canvas, 1)
        )
    })
})

describe('readableFitViewport', () => {
    const canvas = { width: 1000, height: 700 }
    const entryOnScreen = (entry: { x: number; y: number }, viewport: { x: number; y: number; zoom: number }): number =>
        viewport.x + entry.x * viewport.zoom

    it.each([
        { name: 'fits a small workflow at full size', bounds: { x: 0, y: 0, width: 400, height: 300 }, zoom: 1 },
        {
            name: 'keeps a wide workflow readable, for people to pan',
            bounds: { x: 0, y: 0, width: 4000, height: 300 },
            zoom: 0.66,
        },
        { name: 'keeps a long workflow readable too', bounds: { x: 0, y: 0, width: 400, height: 6000 }, zoom: 0.66 },
    ])('$name', ({ bounds, zoom }) => {
        expect(readableFitViewport(bounds, canvas, { x: bounds.width / 2, y: 0 }).zoom).toBeCloseTo(zoom)
    })

    it('starts a workflow too wide to fit at its trigger, in the middle of the canvas', () => {
        const trigger = { x: 2000, y: 0 }

        const viewport = readableFitViewport({ x: 0, y: 0, width: 4000, height: 300 }, canvas, trigger)

        expect(entryOnScreen(trigger, viewport)).toBeCloseTo(500)
    })

    it('keeps the left edge of a wide workflow in view when its trigger sits near that edge', () => {
        const viewport = readableFitViewport({ x: 0, y: 0, width: 4000, height: 300 }, canvas, { x: 100, y: 0 })

        expect(viewport.x).toBeCloseTo(24)
    })
})

describe('stepCountsRequest', () => {
    const now = new Date('2026-10-13T12:00:00Z')

    it('asks for every step and metric of the last seven days of a saved workflow', () => {
        const workflow = { id: 'flow-1', trigger: { type: 'event' }, actions: Array(40).fill(step('a')) } as HogFlow

        expect(stepCountsRequest(workflow, now)).toEqual({
            appSource: 'hog_flow',
            appSourceId: 'flow-1',
            dateFrom: '2026-10-06T12:00:00.000Z',
            dateTo: '2026-10-13T12:00:00.000Z',
            breakdownBy: ['instance_id', 'metric_name'],
            metricName: ['succeeded', 'failed', 'filtered', 'rate_limited', 'triggered'],
            limit: 205,
        })
    })

    it.each([
        { name: 'an unsaved workflow', workflow: { id: 'new', trigger: { type: 'event' } } },
        { name: 'a batch workflow', workflow: { id: 'flow-1', trigger: { type: 'batch' } } },
    ])('skips $name', ({ workflow }) => {
        expect(stepCountsRequest(workflow as HogFlow, now)).toBeNull()
    })

    it.each([
        { name: 'keeps the counts of a saved workflow', trigger: 'event', expected: 50 },
        { name: 'drops counts loaded before the trigger became a batch', trigger: 'batch', expected: undefined },
    ])('$name', ({ trigger, expected }) => {
        const metrics = { email: { actionId: 'email', succeeded: 40, failed: 2, filtered: 8 } }
        const workflow = { id: 'flow-1', trigger: { type: trigger } } as HogFlow

        expect(stepCount(countableStepMetrics(workflow, metrics), 'email')).toBe(expected)
    })
})
