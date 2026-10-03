import { expect, mock, test } from 'claude-code/testing'

const WORLD = {
    width: 6,
    depth: 8,
    textMap: { rows: ['######', '#S...#', '#....#', '######'], unitsPerRow: 2 },
    objects: [{ id: 'ship', name: 'Ship it button', glyph: 'S', color: '#2BA84A' }],
    phrases: [{ id: 'hi', text: 'Hi hogs! 👋' }],
    skins: ['default'],
    walkSpeed: 7,
    limits: { bubbleMs: 6000 },
}

const YOU = {
    id: 'p1',
    name: 'Test Hog',
    skin: 'default',
    client: 'mod',
    x: 4.4,
    y: 3,
    path: [],
    facing: 'left',
    moving: false,
    bubble: null,
}

const STATE = {
    you: YOU,
    players: [YOU, { ...YOU, id: 'p2', name: 'Other Hog', client: 'web', x: 3.2, y: 5 }],
    feed: [{ id: 1, at: 0, text: 'Test Hog waddled in' }],
    objects: { lightsOn: true, doorA: 0, doorB: 0, bugsCaught: 0, deploys: 0 },
    online: 2,
    seq: 1,
    at: 0,
}

const PANE = {
    plugin: 'club-hoguin',
    component: 'Pane',
    requestId: 'club-hoguin',
    viewport: { columns: 160, rows: 50 },
    props: {
        title: 'Club Hoguin',
        isFocused: true,
        bodyColumns: 60,
        placement: 'inline',
        scroll: { offset: 0, bodyRows: 30 },
        view: {},
    },
} as const

type Call = { method: string; path: string; body: unknown }
type Club = {
    calls: Call[]
    panes: { opened: string[]; closed: string[] }
    toasts: string[]
    clock: ReturnType<typeof mock.clock>
    opened: string[][]
}

function setUp(
    on: any,
    {
        placed = true,
        openGate = Promise.resolve(),
        env = { CLUB_HOGUIN_URL: 'http://club.test/' } as Record<string, string>,
        tools = [] as unknown[],
    } = {}
): Club {
    const calls: Call[] = []
    const panes: { opened: string[]; closed: string[] } = { opened: [], closed: [] }
    const toasts: string[] = []
    const opened: string[][] = []
    on('http.fetch', ($: unknown, e: any) => {
        const path = new URL(e.url).pathname
        calls.push({ method: e.init?.method ?? 'GET', path, body: e.init?.body ? JSON.parse(e.init.body) : undefined })
        const data =
            path === '/api/world'
                ? WORLD
                : path === '/api/join'
                  ? { id: 'p1', token: 'secret', name: 'Test Hog', skin: 'default' }
                  : path === '/api/state'
                    ? STATE
                    : path === '/api/events'
                      ? { seq: 1, at: 0, events: [] }
                      : { ok: true }
        return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(data) } }
    })
    on('ui.open', async ($: unknown, e: any) => {
        await openGate
        panes.opened.push(e.id)
        return { value: undefined }
    })
    on('ui.close', ($: unknown, e: any) => {
        panes.closed.push(e.id)
        return { value: undefined }
    })
    on('ui.panes', () => ({
        value: [{ id: 'club-hoguin', title: 'Club Hoguin', isShown: placed, isFocused: false, isPlaced: placed }],
    }))
    on('ui.toast', ($: unknown, e: any) => {
        toasts.push(e.text)
        return { value: undefined }
    })
    on('command.register', () => ({ value: undefined }))
    on('session.start', () => ({ cwd: '/work' }))
    on('turn.start', ($: unknown, e: any) => ({ turnId: e.turnId }))
    on('turn.complete', () => ({ text: '' }))
    on('tool.list', () => ({ value: tools }))
    on('process.run', ($: unknown, e: any) => {
        opened.push(e.argv)
        return { value: { exitCode: 0, stdout: '', stderr: '' } }
    })
    // The tests draw the text map. The picture needs Chrome, which the test environment has not.
    mock.store(on, { showPicture: false })
    mock.env(on, env)
    const clock = mock.clock(on)
    return { calls, panes, toasts, clock, opened }
}

const posts = (calls: Call[], path: string): unknown[] =>
    calls.filter((call) => call.method === 'POST' && call.path === path).map((call) => call.body)

test('/hoguin joins the club, draws the room, and sends preset phrases and moves', async ($, on) => {
    const { calls, panes } = setUp(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.command.run({ command: 'hoguin', args: '' })
    expect(panes.opened).toEqual(['club-hoguin'])
    expect(posts(calls, '/api/join')).toEqual([{ client: 'mod' }])

    for (const surface of ['terminal', 'desktop'] as const) {
        const ui = await $.ui.mount({ ...PANE, surface })
        expect(await ui.find({ type: 'Text', text: /2 here · you are Test Hog/ })).toBeDefined()
        expect(
            await ui.find(surface === 'terminal' ? { type: 'Raster' } : { type: 'Text', text: '█S..@█' })
        ).toBeDefined()
        await ui.unmount()
    }

    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    await ui.press({ key: 'say-hi' })
    await ui.press({ key: 'up' })
    expect(posts(calls, '/api/say')).toEqual([{ phraseId: 'hi' }])
    expect(posts(calls, '/api/move')).toEqual([{ x: 4.4, y: 0 }])

    await $.command.run({ command: 'hoguin', args: '' })
    expect(posts(calls, '/api/leave')).toEqual([{}])
    expect(panes.closed).toEqual(['club-hoguin'])
})

test('a long turn opens the club and the end of the turn closes it', async ($, on) => {
    const { calls, panes, toasts, clock } = setUp(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.turn.start({ text: 'refactor everything', turnId: 't1' })
    await clock.advance(9_000)
    expect(panes.opened).toEqual([])

    await clock.advance(1_000)
    expect(panes.opened).toEqual(['club-hoguin'])
    expect(posts(calls, '/api/join')).toEqual([{ client: 'mod' }])

    await $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 12_000, isAborted: false, usage: null })
    expect(posts(calls, '/api/leave')).toEqual([{}])
    expect(panes.closed).toEqual(['club-hoguin'])
    expect(toasts).toEqual(['Claude is done. Back to work! 🦔'])
})

test('a turn that ends within 10 seconds never opens the club', async ($, on) => {
    const { calls, panes, clock } = setUp(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.turn.start({ text: 'quick question', turnId: 't1' })
    await clock.advance(5_000)
    await $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 5_000, isAborted: false, usage: null })
    await clock.advance(60_000)

    expect(panes.opened).toEqual([])
    expect(posts(calls, '/api/join')).toEqual([])
})

test('a terminal too narrow for the pane gets a hint instead of a hidden hedgehog', async ($, on) => {
    const { calls, panes, toasts, clock } = setUp(on, { placed: false })
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.turn.start({ text: 'refactor everything', turnId: 't1' })
    await clock.advance(10_000)

    expect(panes.closed).toEqual(['club-hoguin'])
    expect(posts(calls, '/api/join')).toEqual([])
    expect(toasts).toEqual(['Claude is busy. Run /hoguin to hang out in Club Hoguin while you wait.'])
})

test('a turn that ends while the pane still opens leaves no pane and no hedgehog', async ($, on) => {
    let finishOpening = (): void => undefined
    const openGate = new Promise<void>((resolve) => (finishOpening = resolve))
    const { calls, panes, clock } = setUp(on, { openGate })
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.turn.start({ text: 'refactor everything', turnId: 't1' })
    await clock.advance(10_000)
    await $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 10_000, isAborted: false, usage: null })
    finishOpening()
    await clock.advance(1_000)

    expect(panes.closed).toEqual(['club-hoguin'])
    expect(posts(calls, '/api/join')).toEqual([])
})

test('/hoguin web opens the club in the browser', async ($, on) => {
    const { opened } = setUp(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    const result = await $.command.run({ command: 'hoguin', args: 'web' })

    expect(opened).toEqual([['open', 'http://club.test/']])
    expect(result.text).toContain('http://club.test/')
})
