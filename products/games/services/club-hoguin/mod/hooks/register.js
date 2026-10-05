// Club Hoguin for Claude Code: a pane that shows the club while Claude works.
// The pane is the real web page. Chrome runs it without a window (see view.mjs), the pane draws its frames,
// and the keys pressed in the pane go to the page. The mod itself never joins the club.

const PANE = 'club-hoguin'
const DEFAULT_URL = 'http://localhost:8642'
const PICTURE_COLUMNS = 72
const PICTURE_ROWS = 22
const AUTO_OPEN_AFTER_MS = 10_000
// A terminal that cannot draw pictures refuses every new frame. This many refusals in a row is the answer.
const REFUSED_FRAMES_MEAN_NO_PICTURES = 10
const NO_PICTURES =
    'The club pane needs a terminal that draws pictures, such as Ghostty or kitty. Run /hoguin web to open the club in your browser.'
const KEYS = [
    { key: 'w', label: 'up' },
    { key: 'a', label: 'left' },
    { key: 's', label: 'down' },
    { key: 'd', label: 'right' },
    { key: 'e', label: 'use' },
]

// CLUB_HOGUIN_URL in the environment of `claude` wins over the default.
let baseUrl = DEFAULT_URL
let autoOpen = true
// False on a surface or in a terminal that has no way to draw a picture. There the pane never opens.
let canDrawPictures = true
// The viewer: Chrome with the club page, and the newest frame it wrote.
let viewer = null
// The phrases of the club, for the labels of the 1 to 9 keys.
let phrases = []
let autoTimer = null
let isOpen = false
let isOpening = false
let isOpeningByTurn = false
// Each open gets a number. A turn that ends while its pane still opens changes the number, and the open stops.
let openNumber = 0
let openedByTurn = false
let hintShown = false

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

// The page says the phrases by number, so the pane needs their words for the key labels.
async function loadPhrases($) {
    try {
        const response = await $.http.fetch(baseUrl + '/api/world', { method: 'GET' })
        phrases = response.ok ? JSON.parse(response.text).phrases.slice(0, 9) : []
    } catch {
        phrases = []
    }
}

// Starts the viewer. Its lines say where its socket is and where each new frame is.
function startViewer($) {
    const workDir = '/tmp/club-hoguin-view-' + Math.random().toString(36).slice(2, 10)
    const current = { frame: null, generation: 0, socketPath: null, failed: null, refusedFrames: 0 }
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
        const isFirst = current.frame === null
        current.generation = Number(rest[0])
        current.frame = rest[1]
        if (current !== viewer || !isOpen) {
            return
        }
        if (isFirst) {
            $.ui.invalidate('ui.render')
        } else {
            void showFrame($, current)
        }
    } else if (word === 'error') {
        current.failed = rest.join(' ')
        $.ui.invalidate('ui.render')
    }
}

async function showFrame($, current) {
    let result
    try {
        result = await $.ui.blit({
            requestId: PANE,
            key: 'picture',
            source: { file: current.frame, format: 'png', generation: current.generation },
        })
    } catch {
        $.ui.invalidate('ui.render')
        return
    }
    if (!result.deny) {
        current.refusedFrames = 0
        return
    }
    current.refusedFrames += 1
    if (current === viewer && isOpen && current.refusedFrames >= REFUSED_FRAMES_MEAN_NO_PICTURES) {
        canDrawPictures = false
        await closeClub($, true)
        $.ui.toast(NO_PICTURES)
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
        // A pane the mod opens by itself waits off screen in a narrow terminal. Do not start Chrome for it.
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
    startViewer($)
    await loadPhrases($)
    $.ui.invalidate('ui.render')
}

async function closeClub($, closePane) {
    await stopViewer($)
    const wasOpen = isOpen
    isOpen = false
    openedByTurn = false
    if (closePane && wasOpen) {
        await $.ui.close({ id: PANE })
    }
}

export function register(on) {
    on('session.start', async ($, e, next) => {
        // Only a terminal has the picture element, and Terminal.app cannot draw one.
        canDrawPictures = e.surface === 'terminal' && (await $.env.get('TERM_PROGRAM')) !== 'Apple_Terminal'
        const url = await $.env.get('CLUB_HOGUIN_URL')
        if (url) {
            baseUrl = url.replace(/\/+$/, '')
        }
        const savedAutoOpen = await $.store.get('autoOpen')
        if (typeof savedAutoOpen === 'boolean') {
            autoOpen = savedAutoOpen
        }
        await $.command.register({
            name: 'hoguin',
            description: 'Open or close Club Hoguin, a place to hang out with other hedgehogs while Claude works',
            argumentHint: '[web|auto on|auto off]',
            immediate: true,
        })
        return next(e)
    })

    on('command.run', { command: 'hoguin' }, async ($, e) => {
        const args = e.args.trim().toLowerCase()
        if (args === 'auto on' || args === 'auto off') {
            autoOpen = args === 'auto on'
            await $.store.set('autoOpen', autoOpen)
            return {
                text: autoOpen
                    ? 'Club Hoguin opens by itself when Claude works for more than 10 seconds.'
                    : 'Club Hoguin opens only when you run /hoguin.',
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
                text: 'Run /hoguin to open or close the club, /hoguin web to open it in the browser, or /hoguin auto on|off to choose if it opens by itself.',
            }
        }
        if (isOpen) {
            await closeClub($, true)
        } else if (!canDrawPictures) {
            return { text: NO_PICTURES }
        } else {
            await openClub($, false)
        }
        return {}
    })

    on('turn.start', async ($, e, next) => {
        if (autoOpen && canDrawPictures && !isOpen && !autoTimer) {
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
            await closeClub($, true)
            $.ui.toast('Claude is done. Back to work! 🦔')
        }
        return result
    })

    on('ui.close', { id: PANE }, async ($, e, next) => {
        const result = await next(e)
        if (e.origin.kind === 'person' && isOpen) {
            await closeClub($, false)
        }
        return result
    })

    on('ui.render', { component: 'Pane' }, async ($, e, next) => {
        if (e.requestId !== PANE) {
            return next(e)
        }
        const { Box, Text, Button, Image } = $.ui.resolve(e)
        if (!viewer || !Image) {
            return Box({ flexDirection: 'column', children: [Text({ dimColor: true, children: ['Waddling in…'] })] })
        }
        const picture = viewer.failed
            ? Text({ color: 'red', wrap: 'wrap', children: ["Can't show the club: " + viewer.failed] })
            : viewer.frame
              ? Image({
                    key: 'picture',
                    source: { file: viewer.frame, format: 'png', generation: viewer.generation },
                    columns: PICTURE_COLUMNS,
                    rows: PICTURE_ROWS,
                    alt: NO_PICTURES,
                })
              : Text({ dimColor: true, children: ['Starting the town… (Chrome opens it without a window)'] })
        const key = ({ key: hotkey, label }) =>
            Button({ key: 'key-' + hotkey, label, hotkey, plain: true, onPress: () => void sendKey($, hotkey) })
        return Box({
            flexDirection: 'column',
            children: [
                picture,
                Box({ flexDirection: 'row', columnGap: 2, flexWrap: 'wrap', children: KEYS.map(key) }),
                Box({
                    flexDirection: 'row',
                    columnGap: 2,
                    flexWrap: 'wrap',
                    children: phrases.map((phrase, index) => key({ key: String(index + 1), label: phrase.text })),
                }),
            ],
        })
    })
}
