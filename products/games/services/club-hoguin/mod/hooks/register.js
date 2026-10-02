// Club Hoguin for Claude Code: a pane where you hang out with other hedgehogs while Claude works.
// A mod has no sockets, so the pane polls the Club Hoguin server over HTTP.

const PANE = 'club-hoguin'
const DEFAULT_URL = 'http://localhost:8642'
const POLL_MS = 500
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

let baseUrl = DEFAULT_URL
let autoJoin = true
let world = null
let session = null
let snapshot = null
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
    return { status: response.status, ok: response.ok, data }
}

async function join($) {
    try {
        if (!world) {
            const described = await request($, 'GET', '/api/world')
            if (!described.ok) {
                throw new Error('world ' + described.status)
            }
            world = described.data
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

async function poll($) {
    if (isPolling) {
        return
    }
    isPolling = true
    try {
        if (session || (await join($))) {
            const state = await request($, 'GET', '/api/state')
            if (state.status === 401) {
                session = null
            } else if (state.ok) {
                snapshot = state.data
                problem = null
            } else {
                problem = 'Club Hoguin answered with status ' + state.status + '. Trying again…'
            }
        }
    } catch {
        problem = UNREACHABLE + baseUrl + '. Trying again…'
    } finally {
        isPolling = false
    }
    $.ui.invalidate('ui.render')
}

async function act($, path, body) {
    if (!session) {
        return
    }
    try {
        const result = await request($, 'POST', path, body)
        const error = result.data && result.data.error
        if (result.status === 401) {
            session = null
        } else if (error === 'too_far') {
            $.ui.toast('Walk closer to something to poke it.')
        } else if (error === 'cooldown') {
            $.ui.toast('Slow down a little, hedgehog.')
        }
    } catch {
        problem = UNREACHABLE + baseUrl + '. Trying again…'
    }
    await poll($)
}

async function walk($, dx, dy) {
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
        await $.command.register({
            name: 'hoguin',
            description: 'Open or close Club Hoguin, a place to hang out with other hedgehogs while Claude works',
            argumentHint: '[auto on|auto off]',
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
        if (args !== '') {
            return {
                text: 'Run /hoguin to open or close the club, or /hoguin auto on|off to choose if it opens by itself.',
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
        const { Box, Text, Button, Raster } = $.ui.resolve(e)
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
            e.surface === 'terminal'
                ? Raster({
                      key: 'map',
                      columns: world.textMap.rows[0].length,
                      rows: world.textMap.rows.length,
                      cells: mapCells(world, snapshot),
                  })
                : Box({
                      flexDirection: 'column',
                      children: mapLines(world, snapshot).map((line) => Text({ wrap: 'truncate', children: [line] })),
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
                onPress: () => void walk($, direction.dx, direction.dy),
            })
        )
        const poke = Button({
            key: 'poke',
            label: 'poke',
            hotkey: 'e',
            plain: true,
            onPress: () => void act($, '/api/poke', {}),
        })
        const phrases = world.phrases.slice(0, 9).map((phrase, index) =>
            Button({
                key: 'say-' + phrase.id,
                label: phrase.text,
                hotkey: String(index + 1),
                plain: true,
                onPress: () => void act($, '/api/say', { phraseId: phrase.id }),
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
