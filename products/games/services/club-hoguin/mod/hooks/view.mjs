// Shows the real Club Hoguin web page in a Claude Code pane. The mod runs this with the node on the machine.
//
// It starts the Chrome on the machine without a window, opens the club in it, and asks Chrome for a picture
// of the page as it changes (the DevTools screencast). Each picture goes to a PNG file that the terminal
// reads and draws in the pane, and the mod sends key presses here over a Unix socket, which go to the page.
// Usage: node view.mjs <club url> <work dir>
import { spawn } from 'node:child_process'
import { mkdirSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { join } from 'node:path'

const [url, workDir] = process.argv.slice(2)
const FRAME_EVERY_MS = 66
const KEY_HELD_MS = 260
// The size of an ordinary browser window, so the page lays out as it does on the web. The terminal scales it.
const VIEW_WIDTH = 1280
const VIEW_HEIGHT = 720

const CHROME_CANDIDATES = [
    process.env.CLUB_HOGUIN_CHROME,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
    'google-chrome',
    'chromium',
    'chromium-browser',
].filter(Boolean)

function say(line) {
    process.stdout.write(line + '\n')
}

function startChrome() {
    return new Promise((resolve, reject) => {
        let index = 0
        const tryNext = () => {
            const binary = CHROME_CANDIDATES[index++]
            if (!binary) {
                reject(new Error('no Chrome found; set CLUB_HOGUIN_CHROME to its path'))
                return
            }
            const child = spawn(
                binary,
                [
                    '--headless=new',
                    '--remote-debugging-port=0',
                    `--user-data-dir=${join(workDir, 'profile')}`,
                    `--window-size=${VIEW_WIDTH},${VIEW_HEIGHT}`,
                    '--hide-scrollbars',
                    '--no-first-run',
                    '--no-default-browser-check',
                    '--mute-audio',
                    '--autoplay-policy=no-user-gesture-required',
                    url,
                ],
                { stdio: ['ignore', 'ignore', 'pipe'] }
            )
            let stderr = ''
            child.stderr.on('data', (chunk) => {
                stderr += chunk
                const match = /DevTools listening on (ws:\/\/[^\s]+)/.exec(stderr)
                if (match) {
                    resolve({ child, browserUrl: match[1] })
                }
            })
            child.on('error', () => tryNext())
            child.on('exit', (code) => {
                if (!/DevTools listening/.test(stderr)) {
                    tryNext()
                } else {
                    say(`chrome exited ${code}`)
                    process.exit(0)
                }
            })
        }
        tryNext()
    })
}

// A small client for the DevTools protocol over the WebSocket that Node has.
class Devtools {
    constructor(socket) {
        this.socket = socket
        this.nextId = 1
        this.pending = new Map()
        this.listeners = new Map()
        socket.addEventListener('message', (message) => {
            const data = JSON.parse(message.data)
            if (data.id && this.pending.has(data.id)) {
                const { resolve, reject } = this.pending.get(data.id)
                this.pending.delete(data.id)
                if (data.error) {
                    reject(new Error(data.error.message))
                } else {
                    resolve(data.result)
                }
            } else if (data.method && this.listeners.has(data.method)) {
                this.listeners.get(data.method)(data.params)
            }
        })
    }

    send(method, params = {}) {
        const id = this.nextId++
        this.socket.send(JSON.stringify({ id, method, params }))
        return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }))
    }

    on(method, listener) {
        this.listeners.set(method, listener)
    }
}

async function main() {
    // Without this check a club that is down shows as Chrome's own error page.
    const origin = new URL(url).origin
    const isUp = await fetch(origin + '/healthz', { signal: AbortSignal.timeout(5000) })
        .then((response) => response.ok)
        .catch(() => false)
    if (!isUp) {
        throw new Error(`Can't reach Club Hoguin at ${origin}. Set CLUB_HOGUIN_URL to the address of a running club.`)
    }
    mkdirSync(workDir, { recursive: true })
    // The frames and the Chrome profile are of no use after the pane closes, however this process ends.
    process.on('exit', () => rmSync(workDir, { recursive: true, force: true }))
    const { child, browserUrl } = await startChrome()
    const port = new URL(browserUrl).port
    let page
    for (let attempt = 0; attempt < 50 && !page; attempt++) {
        const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then((response) => response.json())
        page = targets.find((target) => target.type === 'page' && target.url.startsWith(url.split('?')[0]))
        if (!page) {
            await new Promise((resolve) => setTimeout(resolve, 100))
        }
    }
    if (!page) {
        throw new Error('Chrome opened no page for the club')
    }
    const socket = new WebSocket(page.webSocketDebuggerUrl)
    await new Promise((resolve, reject) => {
        socket.addEventListener('open', resolve)
        socket.addEventListener('error', reject)
    })
    const devtools = new Devtools(socket)
    await devtools.send('Page.enable')
    // The window size of Chrome includes its own frame, so the page is given its size directly.
    await devtools.send('Emulation.setDeviceMetricsOverride', {
        width: VIEW_WIDTH,
        height: VIEW_HEIGHT,
        deviceScaleFactor: 1,
        mobile: false,
    })

    // Frames: Chrome sends one when the page changed; at most one in FRAME_EVERY_MS reaches the pane.
    let frameNumber = 0
    let lastFrameAt = 0
    devtools.on('Page.screencastFrame', (frame) => {
        devtools.send('Page.screencastFrameAck', { sessionId: frame.sessionId }).catch(() => undefined)
        const now = Date.now()
        if (now - lastFrameAt < FRAME_EVERY_MS) {
            return
        }
        lastFrameAt = now
        frameNumber += 1
        const path = join(workDir, `frame-${frameNumber % 3}.png`)
        writeFileSync(path + '.tmp', Buffer.from(frame.data, 'base64'))
        renameSync(path + '.tmp', path)
        say(`frame ${frameNumber} ${path}`)
    })
    await devtools.send('Page.startScreencast', {
        format: 'png',
        maxWidth: VIEW_WIDTH,
        maxHeight: VIEW_HEIGHT,
        everyNthFrame: 1,
    })

    // Keys: a press holds the key down on the page until the presses stop, like a terminal's auto-repeat.
    const held = new Map()
    const keyEvent = (type, key) => {
        const code = /^[a-z]$/.test(key) ? `Key${key.toUpperCase()}` : /^[0-9]$/.test(key) ? `Digit${key}` : key
        const base = { type, key, code, windowsVirtualKeyCode: key.length === 1 ? key.toUpperCase().charCodeAt(0) : 0 }
        return devtools.send(
            'Input.dispatchKeyEvent',
            type === 'keyDown' && key.length === 1 ? { ...base, text: key } : base
        )
    }
    async function press(key) {
        const current = held.get(key)
        if (current) {
            clearTimeout(current)
        } else {
            await keyEvent('keyDown', key)
        }
        held.set(
            key,
            setTimeout(() => {
                held.delete(key)
                keyEvent('keyUp', key).catch(() => undefined)
            }, KEY_HELD_MS)
        )
    }

    const socketPath = join(workDir, 'view.sock')
    rmSync(socketPath, { force: true })
    const server = createServer((request, response) => {
        let body = ''
        request.on('data', (chunk) => (body += chunk))
        request.on('end', async () => {
            if (request.url === '/quit') {
                response.end('bye')
                shutdown()
                return
            }
            if (request.url === '/key') {
                const { key } = JSON.parse(body || '{}')
                if (typeof key === 'string' && key.length > 0 && key.length < 16) {
                    await press(key).catch(() => undefined)
                }
            }
            response.end('ok')
        })
    })
    server.listen(socketPath, () => say(`socket ${socketPath}`))

    function shutdown() {
        server.close()
        child.kill()
        setTimeout(() => process.exit(0), 300)
    }
    process.on('SIGTERM', shutdown)
    process.on('SIGINT', shutdown)
    child.on('exit', () => process.exit(0))
}

main().catch((error) => {
    say(`error ${error.message}`)
    process.exit(1)
})
