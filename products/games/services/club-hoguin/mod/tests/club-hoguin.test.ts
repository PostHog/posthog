import { expect, mock, test } from 'claude-code/testing'

const PANE = {
    plugin: 'club-hoguin',
    component: 'Pane',
    requestId: 'club-hoguin',
    surface: 'terminal',
    viewport: { columns: 160, rows: 50 },
    props: {
        title: 'Club Hoguin',
        isFocused: true,
        bodyColumns: 80,
        placement: 'inline',
        scroll: { offset: 0, bodyRows: 30 },
        view: {},
    },
} as const

const SOCKET = '/tmp/view.sock'
const NEEDS_PICTURES = /needs a terminal that draws pictures/

type Fetch = { url: string; socketPath?: string; body?: unknown }
type Club = {
    fetches: Fetch[]
    spawns: string[][]
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
        // What the viewer process prints. By default: where its socket is, and one frame.
        viewerLines = [`socket ${SOCKET}`, 'frame 1 /tmp/frame-1.png'],
        blitDenied = false,
    } = {}
): Club {
    const fetches: Fetch[] = []
    const spawns: string[][] = []
    const panes: { opened: string[]; closed: string[] } = { opened: [], closed: [] }
    const toasts: string[] = []
    const opened: string[][] = []
    let stopViewer = (): void => undefined
    const viewerStopped = new Promise<void>((resolve) => (stopViewer = resolve))
    on('http.fetch', ($: unknown, e: any) => {
        fetches.push({
            url: e.url,
            socketPath: e.init?.socketPath,
            body: e.init?.body ? JSON.parse(e.init.body) : undefined,
        })
        if (e.url === 'http://view/quit') {
            stopViewer()
        }
        const data = e.url.endsWith('/api/world') ? { phrases: [{ id: 'hi', text: 'Hi hogs! 👋' }] } : {}
        return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(data) } }
    })
    on('process.spawn', async function* ($: unknown, e: any) {
        spawns.push(e.argv)
        yield { stream: 'stdout', text: viewerLines.map((line) => line + '\n').join('') }
        await viewerStopped
        return { value: { code: 0, signal: null } }
    })
    on('ui.blit', () => ({ value: blitDenied ? { deny: 'this terminal draws the alt' } : {} }))
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
    on('process.run', ($: unknown, e: any) => {
        opened.push(e.argv)
        return { value: { exitCode: 0, stdout: '', stderr: '' } }
    })
    mock.store(on, {})
    mock.env(on, env)
    const clock = mock.clock(on)
    return { fetches, spawns, panes, toasts, clock, opened }
}

const toViewer = (fetches: Fetch[], path: string): Fetch[] =>
    fetches.filter((fetch) => fetch.url === 'http://view' + path)

test('/hoguin shows the club page in the pane and sends the keys to it', async ($, on) => {
    const { fetches, spawns, panes } = setUp(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.command.run({ command: 'hoguin', args: '' })
    expect(panes.opened).toEqual(['club-hoguin'])
    expect(spawns).toHaveLength(1)
    expect(spawns[0][1]).toMatch(/hooks\/view\.mjs$/)
    expect(spawns[0][2]).toBe('http://club.test/?pane=1')
    expect(spawns[0].slice(4)).toEqual(['1280', '600'])

    const ui = await $.ui.mount(PANE)
    // The picture is as wide as the pane (80 columns here) and keeps the shape of the page.
    expect((await ui.find({ type: 'Image' }))?.props).toMatchObject({ columns: 80, rows: 18 })
    expect(await ui.find({ type: 'Button', text: 'Hi hogs! 👋' })).toBeDefined()
    await ui.press({ key: 'key-w' })
    await ui.press({ key: 'key-1' })
    expect(toViewer(fetches, '/key')).toEqual([
        { url: 'http://view/key', socketPath: SOCKET, body: { key: 'w' } },
        { url: 'http://view/key', socketPath: SOCKET, body: { key: '1' } },
    ])

    await $.command.run({ command: 'hoguin', args: '' })
    expect(toViewer(fetches, '/quit')).toHaveLength(1)
    expect(panes.closed).toEqual(['club-hoguin'])
})

test('a long turn opens the club and the end of the turn closes it', async ($, on) => {
    const { fetches, spawns, panes, toasts, clock } = setUp(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.turn.start({ text: 'refactor everything', turnId: 't1' })
    await clock.advance(9_000)
    expect(panes.opened).toEqual([])

    await clock.advance(1_000)
    expect(panes.opened).toEqual(['club-hoguin'])
    expect(spawns).toHaveLength(1)

    await $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 12_000, isAborted: false, usage: null })
    expect(toViewer(fetches, '/quit')).toHaveLength(1)
    expect(panes.closed).toEqual(['club-hoguin'])
    expect(toasts).toEqual(['Claude is done. Back to work! 🦔'])
})

test('a turn that ends within 10 seconds never opens the club', async ($, on) => {
    const { spawns, panes, clock } = setUp(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.turn.start({ text: 'quick question', turnId: 't1' })
    await clock.advance(5_000)
    await $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 5_000, isAborted: false, usage: null })
    await clock.advance(60_000)

    expect(panes.opened).toEqual([])
    expect(spawns).toEqual([])
})

test('a terminal too narrow for the pane gets a hint and no Chrome', async ($, on) => {
    const { spawns, panes, toasts, clock } = setUp(on, { placed: false })
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.turn.start({ text: 'refactor everything', turnId: 't1' })
    await clock.advance(10_000)

    expect(panes.closed).toEqual(['club-hoguin'])
    expect(spawns).toEqual([])
    expect(toasts).toEqual(['Claude is busy. Run /hoguin to hang out in Club Hoguin while you wait.'])
})

test('a turn that ends while the pane still opens leaves no pane and no Chrome', async ($, on) => {
    let finishOpening = (): void => undefined
    const openGate = new Promise<void>((resolve) => (finishOpening = resolve))
    const { spawns, panes, clock } = setUp(on, { openGate })
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.turn.start({ text: 'refactor everything', turnId: 't1' })
    await clock.advance(10_000)
    await $.turn.complete({ turnId: 't1', answer: 'done', durationMs: 10_000, isAborted: false, usage: null })
    finishOpening()
    await clock.advance(1_000)

    expect(panes.closed).toEqual(['club-hoguin'])
    expect(spawns).toEqual([])
})

test('/hoguin web opens the club in the browser', async ($, on) => {
    const { opened } = setUp(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    const result = await $.command.run({ command: 'hoguin', args: 'web' })

    expect(opened).toEqual([['open', 'http://club.test/']])
    expect(result.text).toContain('http://club.test/')
})

for (const [place, surface, termProgram] of [
    ['macOS Terminal.app', 'terminal', 'Apple_Terminal'],
    ['the desktop app', 'desktop', 'ghostty'],
] as const) {
    test(`in ${place} the club stays closed and says where it works`, async ($, on) => {
        const { spawns, panes, clock } = setUp(on, {
            env: { CLUB_HOGUIN_URL: 'http://club.test/', TERM_PROGRAM: termProgram },
        })
        await $.session.start({ surface, isInteractive: true, cwd: '/work' })

        const result = await $.command.run({ command: 'hoguin', args: '' })
        await $.turn.start({ text: 'refactor everything', turnId: 't1' })
        await clock.advance(60_000)

        expect(result.text).toMatch(NEEDS_PICTURES)
        expect(panes.opened).toEqual([])
        expect(spawns).toEqual([])
    })
}

test('a terminal that refuses every frame closes the pane, stops Chrome, and says where it works', async ($, on) => {
    const frames = Array.from({ length: 12 }, (_, index) => `frame ${index + 1} /tmp/frame-${index % 3}.png`)
    const { fetches, panes, toasts, clock } = setUp(on, {
        viewerLines: [`socket ${SOCKET}`, ...frames],
        blitDenied: true,
    })
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.command.run({ command: 'hoguin', args: '' })
    await clock.advance(1_000)

    expect(panes.closed).toEqual(['club-hoguin'])
    expect(toViewer(fetches, '/quit')).toHaveLength(1)
    expect(toasts).toHaveLength(1)
    expect(toasts[0]).toMatch(NEEDS_PICTURES)
    expect((await $.command.run({ command: 'hoguin', args: '' })).text).toMatch(NEEDS_PICTURES)
})

test('a club that cannot be reached shows the reason in the pane', async ($, on) => {
    setUp(on, { viewerLines: ["error Can't reach Club Hoguin at http://club.test"] })
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

    await $.command.run({ command: 'hoguin', args: '' })

    const ui = await $.ui.mount(PANE)
    expect(await ui.find({ type: 'Text', text: /Can't reach Club Hoguin at http:\/\/club\.test/ })).toBeDefined()
})

test('a wide, low pane gets a picture that fits its height, and a tiny one says to widen the terminal', async ($, on) => {
    setUp(on)
    await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
    await $.command.run({ command: 'hoguin', args: '' })
    const pane = (bodyColumns: number, bodyRows: number): typeof PANE =>
        ({ ...PANE, props: { ...PANE.props, bodyColumns, scroll: { offset: 0, bodyRows } } }) as typeof PANE

    // 140 columns would need 31 rows. With 20 rows, 2 of them for the keys, the picture is 18 rows.
    const low = await $.ui.mount(pane(140, 20))
    expect((await low.find({ type: 'Image' }))?.props).toMatchObject({ columns: 81, rows: 18 })
    await low.unmount()

    const tiny = await $.ui.mount(pane(140, 10))
    expect(await tiny.find({ type: 'Image' })).toBeUndefined()
    expect(await tiny.find({ type: 'Text', text: /too small to show the club/ })).toBeDefined()
})
