// @ts-check
// The browser client for Club Hoguin. It polls the room state and draws it on one canvas.

const TILE = 24
const SPRITE_SIZE = 48
const POLL_MS = 250
const MOVE_REPEAT_MS = 110
const WALK_FRAME_MS = 70

const OBJECT_EMOJI = {
    flag: '🚩',
    replay: '🎬',
    max: '✨',
    bugs: '🐛',
    'door-a': 'A',
    'door-b': 'B',
    ship: '🚀',
}

const ERROR_MESSAGES = {
    too_far: 'Walk closer to something to poke it.',
    cooldown: 'Slow down a little, hedgehog.',
    club_full: 'The club is full right now. Try again soon.',
}

const KEY_DIRECTIONS = {
    ArrowUp: [0, -1],
    ArrowDown: [0, 1],
    ArrowLeft: [-1, 0],
    ArrowRight: [1, 0],
    w: [0, -1],
    s: [0, 1],
    a: [-1, 0],
    d: [1, 0],
}

const params = new URLSearchParams(window.location.search)
const clientKind = params.get('embed') === '1' ? 'embed' : 'web'

const canvas = /** @type {HTMLCanvasElement} */ (document.getElementById('world'))
const ctx = /** @type {CanvasRenderingContext2D} */ (canvas.getContext('2d'))
const statusEl = /** @type {HTMLElement} */ (document.getElementById('status'))
const phrasesEl = /** @type {HTMLElement} */ (document.getElementById('phrases'))
const feedEl = /** @type {HTMLElement} */ (document.getElementById('feed'))

/** @type {any} */
let world = null
/** @type {string | null} */
let token = null
/** @type {any} */
let snapshot = null
/** @type {{ image: HTMLImageElement, frames: Record<string, { x: number, y: number, w: number, h: number }>, animations: Map<string, string[]> } | null} */
let sprites = null
let lastFeedId = 0
let lastMoveAt = 0
let notice = ''
let noticeUntil = 0
/** @type {Map<string, { x: number, y: number }>} */
const displayed = new Map()

/**
 * @param {string} method
 * @param {string} path
 * @param {object} [body]
 * @param {boolean} [keepalive]
 */
async function api(method, path, body, keepalive = false) {
    /** @type {Record<string, string>} */
    const headers = { 'content-type': 'application/json' }
    if (token) {
        headers['x-hoguin-token'] = token
    }
    /** @type {RequestInit} */
    const init = { method, headers, keepalive }
    if (body !== undefined) {
        init.body = JSON.stringify(body)
    }
    const response = await fetch(path, init)
    const data = await response.json().catch(() => null)
    return { status: response.status, ok: response.ok, data }
}

/** @param {string} text */
function showNotice(text) {
    notice = text
    noticeUntil = performance.now() + 3000
}

async function loadSprites() {
    const image = new Image()
    image.src = '/assets/sprites.png'
    const [atlas] = await Promise.all([
        fetch('/assets/sprites.json').then((response) => response.json()),
        image.decode(),
    ])
    /** @type {Record<string, { x: number, y: number, w: number, h: number }>} */
    const frames = {}
    /** @type {Map<string, string[]>} */
    const animations = new Map()
    for (const [name, entry] of Object.entries(atlas.frames)) {
        frames[name] = entry.frame
        const animation = name.slice(0, name.lastIndexOf('/'))
        animations.set(animation, [...(animations.get(animation) ?? []), name])
    }
    for (const names of animations.values()) {
        names.sort()
    }
    sprites = { image, frames, animations }
}

async function join() {
    const result = await api('POST', '/api/join', { client: clientKind })
    if (!result.ok) {
        throw new Error(result.data?.error ?? 'join_failed')
    }
    token = result.data.token
}

async function poll() {
    try {
        if (!token) {
            await join()
        }
        const result = await api('GET', '/api/state')
        if (result.status === 401) {
            token = null
        } else if (result.ok) {
            snapshot = result.data
            renderFeed()
        }
    } catch (error) {
        const code = error instanceof Error ? error.message : ''
        showNotice(ERROR_MESSAGES[code] ?? "Can't reach the club. Trying again…")
    }
    window.setTimeout(poll, POLL_MS)
}

/** @param {string} path @param {object} body */
async function act(path, body) {
    if (!token) {
        return
    }
    try {
        const result = await api('POST', path, body)
        if (!result.ok && result.data?.error) {
            showNotice(ERROR_MESSAGES[result.data.error] ?? 'That did not work. Try again.')
        }
    } catch {
        showNotice("Can't reach the club. Trying again…")
    }
}

/** @param {number} dx @param {number} dy */
function walk(dx, dy) {
    const you = snapshot?.you
    const now = performance.now()
    if (!you || now - lastMoveAt < MOVE_REPEAT_MS) {
        return
    }
    lastMoveAt = now
    void act('/api/move', { x: you.x + dx * 2, y: you.y + dy * 2 })
}

function renderPhrases() {
    world.phrases.forEach((/** @type {{ id: string, text: string }} */ phrase, /** @type {number} */ index) => {
        const button = document.createElement('button')
        button.type = 'button'
        const key = document.createElement('kbd')
        key.textContent = String(index + 1)
        button.append(key, phrase.text)
        button.addEventListener('click', () => void act('/api/say', { phraseId: phrase.id }))
        phrasesEl.append(button)
    })
}

function renderFeed() {
    const feed = snapshot?.feed ?? []
    const newest = feed.length > 0 ? feed[feed.length - 1].id : 0
    if (newest === lastFeedId) {
        return
    }
    lastFeedId = newest
    feedEl.replaceChildren(
        ...feed
            .slice()
            .reverse()
            .map((/** @type {{ text: string }} */ entry) => {
                const item = document.createElement('li')
                item.textContent = entry.text
                return item
            })
    )
}

/** @param {string} text @param {number} centerX @param {number} bottomY */
function drawBubble(text, centerX, bottomY) {
    ctx.font = '13px system-ui, sans-serif'
    const width = Math.min(ctx.measureText(text).width + 16, 260)
    const x = Math.min(Math.max(centerX - width / 2, 2), canvas.width - width - 2)
    const y = Math.max(bottomY - 26, 2)
    ctx.fillStyle = '#ffffff'
    ctx.strokeStyle = '#151515'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.roundRect(x, y, width, 22, 8)
    ctx.fill()
    ctx.stroke()
    ctx.fillStyle = '#151515'
    ctx.textAlign = 'left'
    ctx.textBaseline = 'middle'
    ctx.fillText(text, x + 8, y + 11, width - 16)
}

function drawRoom() {
    const lightsOn = snapshot?.objects.lightsOn ?? true
    ctx.fillStyle = lightsOn ? '#eeefe9' : '#3b3d45'
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    world.rows.forEach((/** @type {string} */ row, /** @type {number} */ y) => {
        for (let x = 0; x < row.length; x++) {
            if (row[x] === '#') {
                ctx.fillStyle = '#151515'
                ctx.fillRect(x * TILE, y * TILE, TILE, TILE)
            } else if (row[x] === '~') {
                ctx.fillStyle = lightsOn ? '#8fa5ff' : '#2b3a7a'
                ctx.fillRect(x * TILE, y * TILE, TILE, TILE)
            }
        }
    })
    for (const object of world.objects) {
        const x = object.x * TILE
        const y = object.y * TILE
        const width = object.w * TILE
        const height = object.h * TILE
        ctx.fillStyle = object.color
        ctx.beginPath()
        ctx.roundRect(x + 2, y + 2, width - 4, height - 4, 6)
        ctx.fill()
        ctx.font = 'bold 16px system-ui, sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillStyle = '#ffffff'
        ctx.fillText(OBJECT_EMOJI[object.id] ?? object.glyph, x + width / 2, y + height / 2)
        ctx.font = '11px system-ui, sans-serif'
        ctx.fillStyle = lightsOn ? '#151515' : '#eeefe9'
        const labelY = object.y + object.h >= world.height - 1 ? y - 8 : y + height + 9
        ctx.fillText(object.name, x + width / 2, labelY)
    }
}

/** @param {any} player @param {number} now @param {number} dt */
function drawPlayer(player, now, dt) {
    const shown = displayed.get(player.id) ?? { x: player.x, y: player.y }
    const blend = Math.min(1, dt * 12)
    shown.x += (player.x - shown.x) * blend
    shown.y += (player.y - shown.y) * blend
    displayed.set(player.id, shown)

    const centerX = shown.x * TILE + TILE / 2
    const bottomY = shown.y * TILE + TILE
    const animation = sprites?.animations.get(`skins/${player.skin}/${player.moving ? 'walk' : 'idle'}`)
    const frameName = animation?.[player.moving ? Math.floor(now / WALK_FRAME_MS) % animation.length : 0]
    const frame = frameName ? sprites?.frames[frameName] : undefined
    if (sprites && frame) {
        ctx.save()
        ctx.translate(centerX, bottomY - SPRITE_SIZE)
        if (player.facing === 'left') {
            ctx.scale(-1, 1)
        }
        ctx.drawImage(sprites.image, frame.x, frame.y, frame.w, frame.h, -SPRITE_SIZE / 2, 0, SPRITE_SIZE, SPRITE_SIZE)
        ctx.restore()
    } else {
        ctx.fillStyle = '#f54e00'
        ctx.beginPath()
        ctx.arc(centerX, bottomY - TILE / 2, TILE / 2.5, 0, Math.PI * 2)
        ctx.fill()
    }

    const isYou = player.id === snapshot?.you?.id
    const label = `${player.client === 'mod' ? '⏳ ' : ''}${player.name}${isYou ? ' (you)' : ''}`
    ctx.font = `${isYou ? 'bold ' : ''}11px system-ui, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillStyle = isYou ? '#f54e00' : (snapshot?.objects.lightsOn ?? true) ? '#151515' : '#eeefe9'
    ctx.fillText(label, centerX, bottomY + 1)
    if (player.bubble) {
        drawBubble(player.bubble, centerX, bottomY - SPRITE_SIZE)
    }
}

let lastFrameAt = performance.now()

/** @param {number} now */
function frame(now) {
    const dt = (now - lastFrameAt) / 1000
    lastFrameAt = now
    if (world) {
        drawRoom()
        const players = [...(snapshot?.players ?? [])].sort((a, b) => a.y - b.y)
        const ids = new Set(players.map((player) => player.id))
        for (const id of displayed.keys()) {
            if (!ids.has(id)) {
                displayed.delete(id)
            }
        }
        for (const player of players) {
            drawPlayer(player, now, dt)
        }
    }
    if (now < noticeUntil) {
        statusEl.textContent = notice
    } else if (snapshot?.you) {
        const others = snapshot.online - 1
        statusEl.textContent = `You are ${snapshot.you.name}. ${others === 1 ? '1 other hedgehog is' : `${others} other hedgehogs are`} here.`
    }
    window.requestAnimationFrame(frame)
}

canvas.addEventListener('click', (event) => {
    const rect = canvas.getBoundingClientRect()
    const x = Math.floor(((event.clientX - rect.left) / rect.width) * world.width)
    const y = Math.floor(((event.clientY - rect.top) / rect.height) * world.height)
    void act('/api/move', { x, y })
})

window.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey || !world) {
        return
    }
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key
    const direction = KEY_DIRECTIONS[key]
    if (direction) {
        event.preventDefault()
        walk(direction[0], direction[1])
    } else if (key === 'e' && !event.repeat) {
        void act('/api/poke', {})
    } else if (/^[1-9]$/.test(key) && !event.repeat) {
        const phrase = world.phrases[Number(key) - 1]
        if (phrase) {
            void act('/api/say', { phraseId: phrase.id })
        }
    }
})

window.addEventListener('pagehide', () => {
    if (token) {
        void api('POST', '/api/leave', {}, true).catch(() => undefined)
    }
})

async function start() {
    if (clientKind === 'embed') {
        document.body.classList.add('embed')
    }
    const result = await api('GET', '/api/world').catch(() => null)
    if (!result?.ok) {
        statusEl.textContent = "Can't reach the club. Refresh the page to try again."
        return
    }
    world = result.data
    renderPhrases()
    window.requestAnimationFrame(frame)
    loadSprites().catch(() => showNotice('The hedgehog sprites did not load, so everyone is a dot today.'))
    void poll()
}

void start()
