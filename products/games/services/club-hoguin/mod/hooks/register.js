// Club Hoguin for Claude Code: a pane where you hang out with other hedgehogs while Claude works.
// A mod has no sockets, so the pane polls the Club Hoguin server over HTTP for new events.
import { positionAt } from './walk.js'

const PANE = 'club-hoguin'
const DEFAULT_URL = 'http://localhost:8642'
const POLL_MS = 500
// The picture of the town is drawn again this often while the pane shows it.
const PICTURE_COLUMNS = 72
const PICTURE_ROWS = 22
const AUTO_OPEN_AFTER_MS = 10_000
const STEP = 3
const FEED_LINES = 4
const DEFAULT_COLOR = 0x01000000
const SKIN_COLORS = { default: 0xd4a373, spiderhog: 0xe63946, robohog: 0xa8dadc, hogzilla: 0x2ba84a }
const UNREACHABLE = "Can't reach Club Hoguin at "
const DIRECTIONS = [
    { key: 'up', hotkey: 'w', dx: 0, dy: -1 },
    { key: 'left', hotkey: 'a', dx: -1, dy: 0 },
    { key: 'down', hotkey: 's', dx: 0, dy: 1 },
    { key: 'right', hotkey: 'd', dx: 1, dy: 0 },
]

// CLUB_HOGUIN_URL in the environment of `claude` wins over the default.
let baseUrl = DEFAULT_URL
let autoJoin = true
// The pane shows a picture of the town where the terminal can draw one. `/hoguin map` switches to text.
let showPicture = true
// The viewer: the real web page, run by Chrome without a window and shown as pictures (see view.mjs).
let viewer = null
let world = null
let session = null
let snapshot = null
// The town as the events describe it. `snapshot` is a view of it, taken whenever something is drawn.
let model = null
let problem = null
let pollTimer = null
let autoTimer = null
let isPolling = false
let isOpen = false
let isOpening = false
let isOpeningByTurn = false
// Each open gets a number. A turn that ends while its pane still opens changes the number, and the open stops.
let openNumber = 0
let openedByTurn = false
let hintShown = false
// A refused action shows a toast at most this often, so holding a key does not flood the screen.
let lastToastAt = -Infinity
const TOAST_EVERY_MS = 4000

async function request($, method, path, body) {
    const headers = { 'content-type': 'application/json' }
    if (session) {
        headers['x-hoguin-token'] = session.token
    }
    const init = body === undefined ? { method, headers } : { method, headers, body: JSON.stringify(body) }
    const response = await $.http.fetch(baseUrl + path, init)
    let data = null
    try {
        data = JSON.parse(response.text)
    } catch {
        data = null
    }
    return { status: response.status, ok: response.ok, data, text: response.text }
}

// Opens the club in the browser of the person. `open` is macOS; `xdg-open` is Linux.
async function openInBrowser($, url) {
    for (const opener of ['open', 'xdg-open']) {
        try {
            const result = await $.process.run([opener, url], { timeoutMs: 5000 })
            if (result.exitCode === 0) {
                return true
            }
        } catch {
            // Try the next opener.
        }
    }
    return false
}

// The town's description: the map, the phrases, the speed. Every mode needs it, the viewer included.
async function describeWorld($) {
    if (world) {
        return true
    }
    try {
        const described = await request($, 'GET', '/api/world')
        if (!described.ok) {
            throw new Error('world ' + described.status)
        }
        world = described.data
        return true
    } catch {
        problem = UNREACHABLE + baseUrl + '. Set CLUB_HOGUIN_URL to the address of a running server.'
        return false
    }
}

async function join($) {
    try {
        if (!(await describeWorld($))) {
            return false
        }
        const joined = await request($, 'POST', '/api/join', { client: 'mod' })
        if (joined.status === 503) {
            problem = 'Club Hoguin is full right now. Try again soon.'
            return false
        }
        if (joined.status === 429) {
            problem = 'Too many hedgehogs from your network are here. Close another Club Hoguin tab or pane.'
            return false
        }
        if (!joined.ok) {
            throw new Error('join ' + joined.status)
        }
        session = joined.data
        if (!isOpen) {
            // The pane closed while the join was on its way, so the new hedgehog leaves at once.
            await request($, 'POST', '/api/leave', {})
            session = null
            return false
        }
        problem = null
        return true
    } catch {
        problem = UNREACHABLE + baseUrl + '. Set CLUB_HOGUIN_URL to the address of a running server.'
        return false
    }
}

// Loads a snapshot of the town, or applies the events after the last one seen.
function load($, data) {
    if (world && data.serverId !== world.serverId) {
        // The server started again, with new phrases and objects. The next join reads them.
        world = null
        session = null
        model = null
        return
    }
    model = {
        seq: data.seq,
        // The server clock minus the clock of this process. Every hedgehog's position follows the server clock.
        offset: data.at - $.clock.now(),
        objects: data.objects,
        feed: data.feed.map((entry) => entry.text),
        players: new Map(
            data.players.map((player) => [
                player.id,
                { ...player, walk: { from: { x: player.x, y: player.y }, path: player.path, at: data.at } },
            ])
        ),
    }
}

function applyEvent(event) {
    if (!model || event.seq <= model.seq) {
        return
    }
    model.seq = event.seq
    if (event.kind === 'join') {
        model.players.set(event.player.id, {
            ...event.player,
            walk: { from: { x: event.player.x, y: event.player.y }, path: [], at: event.at },
        })
    } else if (event.kind === 'leave') {
        model.players.delete(event.id)
    } else if (event.kind === 'walk') {
        const player = model.players.get(event.id)
        if (player) {
            player.walk = { from: event.from, path: event.path, at: event.at }
        }
    } else if (event.kind === 'say') {
        const player = model.players.get(event.id)
        if (player) {
            player.bubble = event.phrase
            player.bubbleUntil = event.at + world.limits.bubbleMs
        }
    } else if (event.kind === 'look') {
        const player = model.players.get(event.id)
        if (player) {
            player.skin = event.skin
            player.hat = event.hat
        }
    } else if (event.kind === 'poke') {
        model.objects = event.objects
    }
    if (event.text) {
        model.feed = [...model.feed, event.text].slice(-20)
    }
}

// The town right now: every hedgehog where its walk puts it at this moment.
function view($) {
    if (!model) {
        return null
    }
    const now = $.clock.now() + model.offset
    const players = [...model.players.values()].map((player) => {
        const position = positionAt(player.walk, world.walkSpeed, now)
        return {
            ...player,
            x: position.x,
            y: position.y,
            facing: position.facing || player.facing,
            moving: position.moving,
            bubble: player.bubble && now < player.bubbleUntil ? player.bubble : null,
        }
    })
    return {
        you: session ? (players.find((player) => player.id === session.id) ?? null) : null,
        players,
        feed: model.feed.map((text) => ({ text })),
        objects: model.objects,
        online: players.length,
    }
}

async function poll($) {
    if (isPolling) {
        return
    }
    isPolling = true
    try {
        if ((await describeWorld($)) && (session || usesViewer() || (await join($)))) {
            const response = model
                ? await request($, 'GET', '/api/events?since=' + model.seq)
                : await request($, 'GET', '/api/state')
            if (response.status === 401) {
                session = null
                model = null
            } else if (response.ok) {
                if (response.data.resync) {
                    load($, response.data.snapshot)
                } else if (response.data.events) {
                    model.offset = response.data.at - $.clock.now()
                    response.data.events.forEach(applyEvent)
                } else {
                    load($, response.data)
                }
                snapshot = view($)
                problem = null
            } else {
                problem = 'Club Hoguin answered with status ' + response.status + '. Trying again…'
            }
        }
    } catch {
        problem = UNREACHABLE + baseUrl + '. Trying again…'
    } finally {
        isPolling = false
    }
    $.ui.invalidate('ui.render')
}

// Starts the viewer. Its lines say where its socket is and where each new picture is.
function startViewer($) {
    if (viewer) {
        return
    }
    const workDir = '/tmp/club-hoguin-view-' + Math.random().toString(36).slice(2, 10)
    const current = { frame: null, generation: 0, socketPath: null, workDir, failed: null }
    viewer = current
    let stream
    try {
        stream = $.process.spawn({
            argv: ['node', $.plugin.root + '/hooks/view.mjs', baseUrl + '/?pane=1', workDir],
        })
    } catch (error) {
        current.failed = String(error)
        return
    }
    void (async () => {
        try {
            let rest = ''
            for await (const chunk of stream) {
                if (chunk.stream !== 'stdout') {
                    continue
                }
                rest += chunk.text
                const lines = rest.split('\n')
                rest = lines.pop()
                lines.forEach((line) => readViewerLine($, current, line))
            }
        } catch (error) {
            current.failed = String(error)
        }
        if (current === viewer && !current.failed) {
            current.failed = 'The viewer stopped.'
        }
        $.ui.invalidate('ui.render')
    })()
}

function readViewerLine($, current, line) {
    const [word, ...rest] = line.trim().split(' ')
    if (word === 'socket') {
        current.socketPath = rest[0]
    } else if (word === 'frame') {
        const first = current.frame === null
        current.generation = Number(rest[0])
        current.frame = rest[1]
        if (current !== viewer || !isOpen) {
            return
        }
        if (first) {
            $.ui.invalidate('ui.render')
        } else {
            $.ui
                .blit({
                    requestId: PANE,
                    key: 'picture',
                    source: { file: current.frame, format: 'png', generation: current.generation },
                })
                .catch(() => $.ui.invalidate('ui.render'))
        }
    } else if (word === 'error') {
        current.failed = rest.join(' ')
        $.ui.invalidate('ui.render')
    }
}

async function stopViewer($) {
    const current = viewer
    viewer = null
    if (current && current.socketPath) {
        try {
            await $.http.fetch('http://view/quit', { method: 'POST', socketPath: current.socketPath })
        } catch {
            // The viewer exits by itself when Chrome goes.
        }
    }
}

// A key for the page in the viewer. It goes down, and comes up when the presses stop.
async function sendKey($, key) {
    if (!viewer || !viewer.socketPath) {
        return
    }
    try {
        await $.http.fetch('http://view/key', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ key }),
            socketPath: viewer.socketPath,
        })
    } catch {
        // A lost key press is not worth a message.
    }
}

const usesViewer = () => showPicture && viewer !== null && viewer.failed === null

async function act($, path, body) {
    if (!session) {
        return
    }
    try {
        const result = await request($, 'POST', path, body)
        const error = result.data && result.data.error
        const now = $.clock.now()
        if (result.status === 401) {
            session = null
        } else if (error === 'too_far' && now - lastToastAt > TOAST_EVERY_MS) {
            lastToastAt = now
            $.ui.toast('Walk closer to something to poke it.')
        } else if (
            (error === 'cooldown' || error === 'too_many_actions') &&
            path !== '/api/move' &&
            now - lastToastAt > TOAST_EVERY_MS
        ) {
            lastToastAt = now
            $.ui.toast('Slow down a little, hedgehog.')
        }
    } catch {
        problem = UNREACHABLE + baseUrl + '. Trying again…'
    }
    await poll($)
}

async function walk($, dx, dy) {
    snapshot = view($)
    const you = snapshot && snapshot.you
    if (you) {
        await act($, '/api/move', { x: you.x + dx * STEP, y: you.y + dy * STEP })
    }
}

async function openClub($, byTurn) {
    if (isOpen || isOpening) {
        return
    }
    isOpening = true
    isOpeningByTurn = byTurn
    const number = ++openNumber
    try {
        await showClub($, byTurn, number)
    } finally {
        isOpening = false
    }
}

async function showClub($, byTurn, number) {
    const pane = { id: PANE, title: 'Club Hoguin', closeOnEscape: true }
    await $.ui.open(byTurn ? pane : { ...pane, focus: true })
    if (number !== openNumber) {
        await $.ui.close({ id: PANE })
        return
    }
    if (byTurn) {
        // A pane the mod opens by itself waits off screen in a narrow terminal. Do not join the club from there.
        const panes = await $.ui.panes()
        if (!panes.some((candidate) => candidate.id === PANE && candidate.isPlaced)) {
            await $.ui.close({ id: PANE })
            if (!hintShown) {
                hintShown = true
                $.ui.toast('Claude is busy. Run /hoguin to hang out in Club Hoguin while you wait.')
            }
            return
        }
    }
    isOpen = true
    openedByTurn = byTurn
    if (showPicture) {
        startViewer($)
    }
    if (!pollTimer) {
        pollTimer = $.clock.every(POLL_MS, () => {
            void poll($)
        })
    }
    await poll($)
}

async function leaveClub($, closePane) {
    if (pollTimer) {
        pollTimer.cancel()
        pollTimer = null
    }
    await stopViewer($)
    const wasOpen = isOpen
    isOpen = false
    openedByTurn = false
    if (session) {
        try {
            await request($, 'POST', '/api/leave', {})
        } catch {
            // The server drops idle hedgehogs by itself.
        }
    }
    session = null
    snapshot = null
    model = null
    problem = null
    if (closePane && wasOpen) {
        await $.ui.close({ id: PANE })
    }
}

// The server sends a map of text characters. One character covers 1 unit from west to east
// and textMap.unitsPerRow units from north to south.
function tileAt(currentWorld, currentSnapshot, column, row) {
    const isHere = (player) =>
        Math.floor(player.x) === column && Math.floor(player.y / currentWorld.textMap.unitsPerRow) === row
    const you = currentSnapshot.you
    if (you && isHere(you)) {
        return { char: '@', fg: 0x151515, bg: 0xf54e00 }
    }
    const player = currentSnapshot.players.find(isHere)
    if (player) {
        return { char: '@', fg: SKIN_COLORS[player.skin] || 0xffffff, bg: DEFAULT_COLOR }
    }
    const char = currentWorld.textMap.rows[row][column]
    const object = currentWorld.objects.find((candidate) => candidate.glyph === char)
    if (object) {
        return { char, fg: 0x151515, bg: Number.parseInt(object.color.slice(1), 16) }
    }
    if (char === '#') {
        return { char: '█', fg: 0x9a9a9a, bg: DEFAULT_COLOR }
    }
    if (char === '~') {
        return { char: '~', fg: 0x7fd4ff, bg: DEFAULT_COLOR }
    }
    if (char === '^') {
        return { char: '^', fg: 0xff9a3c, bg: DEFAULT_COLOR }
    }
    return { char: '.', fg: currentSnapshot.objects.lightsOn ? 0x6b6b6b : 0x2e2e2e, bg: DEFAULT_COLOR }
}

function mapCells(currentWorld, currentSnapshot) {
    const words = []
    currentWorld.textMap.rows.forEach((line, row) => {
        for (let column = 0; column < line.length; column++) {
            const tile = tileAt(currentWorld, currentSnapshot, column, row)
            words.push(tile.char.codePointAt(0), tile.fg, tile.bg)
        }
    })
    return new Uint8Array(Uint32Array.from(words).buffer).toBase64()
}

function mapLines(currentWorld, currentSnapshot) {
    return currentWorld.textMap.rows.map((line, row) => {
        let text = ''
        for (let column = 0; column < line.length; column++) {
            text += tileAt(currentWorld, currentSnapshot, column, row).char
        }
        return text
    })
}

export function register(on) {
    on('session.start', async ($, e, next) => {
        const url = await $.env.get('CLUB_HOGUIN_URL')
        if (url) {
            baseUrl = url.replace(/\/+$/, '')
        }
        const savedAutoJoin = await $.store.get('autoJoin')
        if (typeof savedAutoJoin === 'boolean') {
            autoJoin = savedAutoJoin
        }
        const savedPicture = await $.store.get('showPicture')
        if (typeof savedPicture === 'boolean') {
            showPicture = savedPicture
        }
        await $.command.register({
            name: 'hoguin',
            description: 'Open or close Club Hoguin, a place to hang out with other hedgehogs while Claude works',
            argumentHint: '[web|map|picture|auto on|auto off]',
            immediate: true,
        })
        return next(e)
    })

    on('command.run', { command: 'hoguin' }, async ($, e) => {
        const args = e.args.trim().toLowerCase()
        if (args === 'auto on' || args === 'auto off') {
            autoJoin = args === 'auto on'
            await $.store.set('autoJoin', autoJoin)
            return {
                text: autoJoin
                    ? 'Club Hoguin opens by itself when Claude works for more than 10 seconds.'
                    : 'Club Hoguin opens only when you run /hoguin.',
            }
        }
        if (args === 'map' || args === 'picture') {
            showPicture = args === 'picture'
            await $.store.set('showPicture', showPicture)
            if (isOpen) {
                if (showPicture) {
                    startViewer($)
                } else {
                    await stopViewer($)
                }
            }
            $.ui.invalidate('ui.render')
            return {
                text: showPicture
                    ? 'The pane shows a picture of the town. Run /hoguin map for the text map.'
                    : 'The pane shows the text map. Run /hoguin picture for the picture.',
            }
        }
        if (args === 'web') {
            const url = baseUrl + '/'
            const opened = await openInBrowser($, url)
            return {
                text: opened
                    ? 'Club Hoguin is open in your browser: ' + url
                    : 'Open Club Hoguin in your browser: ' + url,
            }
        }
        if (args !== '') {
            return {
                text: 'Run /hoguin to open or close the club, /hoguin web to open it in the browser, /hoguin map or picture to choose how the pane draws it, or /hoguin auto on|off to choose if it opens by itself.',
            }
        }
        if (isOpen) {
            await leaveClub($, true)
        } else {
            await openClub($, false)
        }
        return {}
    })

    on('turn.start', async ($, e, next) => {
        if (autoJoin && !isOpen && !autoTimer) {
            autoTimer = $.clock.after(AUTO_OPEN_AFTER_MS, () => {
                autoTimer = null
                void openClub($, true)
            })
        }
        return next(e)
    })

    on('turn.complete', async ($, e, next) => {
        const result = await next(e)
        if (e.agentId) {
            return result
        }
        if (autoTimer) {
            autoTimer.cancel()
            autoTimer = null
        }
        if (isOpening && isOpeningByTurn) {
            openNumber++
        }
        if (isOpen && openedByTurn) {
            await leaveClub($, true)
            $.ui.toast('Claude is done. Back to work! 🦔')
        }
        return result
    })

    on('ui.close', { id: PANE }, async ($, e, next) => {
        const result = await next(e)
        if (e.origin.kind === 'person' && isOpen) {
            await leaveClub($, false)
        }
        return result
    })

    on('ui.render', { component: 'Pane' }, async ($, e, next) => {
        if (e.requestId !== PANE) {
            return next(e)
        }
        const { Box, Text, Button, Raster, Image } = $.ui.resolve(e)
        snapshot = view($)
        const you = snapshot && snapshot.you
        const header = Text({
            bold: true,
            children: [you ? '🦔 Club Hoguin · ' + snapshot.online + ' here · you are ' + you.name : '🦔 Club Hoguin'],
        })
        if (!world || !snapshot) {
            return Box({
                flexDirection: 'column',
                children: [
                    header,
                    Text({ dimColor: !problem, wrap: 'wrap', children: [problem || 'Waddling in…'] }),
                    Button({ key: 'retry', label: 'Try again', hotkey: 'r', plain: true, onPress: () => void poll($) }),
                ],
            })
        }

        const map =
            e.surface === 'terminal' && showPicture && viewer && viewer.frame && !viewer.failed
                ? Image({
                      key: 'picture',
                      source: { file: viewer.frame, format: 'png', generation: viewer.generation },
                      columns: PICTURE_COLUMNS,
                      rows: PICTURE_ROWS,
                      alt: mapLines(world, snapshot).join('\n'),
                  })
                : e.surface === 'terminal' && showPicture && viewer && !viewer.failed
                  ? Text({ dimColor: true, children: ['Starting the town… (Chrome opens it without a window)'] })
                  : e.surface === 'terminal' && showPicture && viewer && viewer.failed
                    ? Text({
                          color: 'red',
                          wrap: 'wrap',
                          children: [
                              'The viewer could not start: ' + viewer.failed + ' Run /hoguin map for the text map.',
                          ],
                      })
                    : e.surface === 'terminal'
                      ? Raster({
                            key: 'map',
                            columns: world.textMap.rows[0].length,
                            rows: world.textMap.rows.length,
                            cells: mapCells(world, snapshot),
                        })
                      : Box({
                            flexDirection: 'column',
                            children: mapLines(world, snapshot).map((line) =>
                                Text({ wrap: 'truncate', children: [line] })
                            ),
                        })
        const legend = world.objects
            .filter((object, index, all) => all.findIndex((other) => other.glyph === object.glyph) === index)
            .map((object) => object.glyph + ' ' + object.name)
            .join('  ')
        const feed = snapshot.feed.slice(-FEED_LINES).map((entry) => Text({ wrap: 'truncate', children: [entry.text] }))
        const moves = DIRECTIONS.map((direction) =>
            Button({
                key: direction.key,
                label: direction.key,
                hotkey: direction.hotkey,
                plain: true,
                onPress: () =>
                    usesViewer() ? void sendKey($, direction.hotkey) : void walk($, direction.dx, direction.dy),
            })
        )
        const poke = Button({
            key: 'poke',
            label: 'poke',
            hotkey: 'e',
            plain: true,
            onPress: () => (usesViewer() ? void sendKey($, 'e') : void act($, '/api/poke', {})),
        })
        const phrases = world.phrases.slice(0, 9).map((phrase, index) =>
            Button({
                key: 'say-' + phrase.id,
                label: phrase.text,
                hotkey: String(index + 1),
                plain: true,
                onPress: () =>
                    usesViewer()
                        ? void sendKey($, String(index + 1))
                        : void act($, '/api/say', { phraseId: phrase.id }),
            })
        )

        return Box({
            flexDirection: 'column',
            children: [
                header,
                ...(problem ? [Text({ color: 'red', wrap: 'wrap', children: [problem] })] : []),
                map,
                Text({ dimColor: true, wrap: 'wrap', children: [legend + '  @ hedgehogs (you are orange)'] }),
                ...feed,
                Box({ flexDirection: 'row', columnGap: 2, flexWrap: 'wrap', children: [...moves, poke] }),
                Box({ flexDirection: 'row', columnGap: 2, flexWrap: 'wrap', children: phrases }),
            ],
        })
    })
}
