// The browser client for Club Hoguin. It polls the room state, draws Hog Town, and sends what the player does.
import { createHogs, loadSprites } from '/hogs.js'
import { THREE } from '/kit.js'
import { createTown } from '/town.js'

const RECONNECT_MS = 2000
const KEY_WALK_MS = 120
const KEY_WALK_REACH = 2.5
const MAX_ID = 'npc-max'
const LOOK_KEY = 'club-hoguin-look'

const ERROR_MESSAGES = {
    too_far: 'Walk closer to something to use it.',
    cooldown: 'Slow down a little, hedgehog.',
    club_full: 'The club is full right now. Trying again soon.',
    too_many_from_address: 'Too many hedgehogs from your network are here. Close another Club Hoguin tab or pane.',
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

const $ = (/** @type {string} */ id) => /** @type {HTMLElement} */ (document.getElementById(id))
const stage = $('stage')
const canvas = /** @type {HTMLCanvasElement} */ ($('world'))
const labels = $('labels')

/** @type {any} */
let world = null
/** @type {ReturnType<typeof createTown>} */
let town
/** @type {ReturnType<typeof createHogs>} */
let hogs
/** @type {Awaited<ReturnType<typeof loadSprites>>} */
let sprites
/** @type {string | null} */
let token = null
/** @type {{ skin: string, hat: string | null } | null} */
let look = null
/** @type {string | null} */
let youId = null
/** @type {any} */
let objects = null
/** @type {string[]} */
let feed = []
// The server clock minus the browser clock. Every hedgehog's position follows the server clock.
let clockOffset = 0
/** @type {EventSource | null} */
let stream = null
let seenSeq = 0
let stageWidth = 1
let stageHeight = 1
let hasWalked = false
/** @type {string | null} */
let hoveredObject = null
let maxSpeaksUntil = 0
let noticeUntil = 0
/** @type {Set<string>} */
const heldKeys = new Set()
let lastKeyWalkAt = 0

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
    $('notice').textContent = text
    $('notice').hidden = false
    noticeUntil = performance.now() + 3200
}

// ---- Talking to the server -----------------------------------------------------------------------------

const serverNow = () => Date.now() + clockOffset

async function join() {
    const joined = await api('POST', '/api/join', { client: clientKind, skin: look?.skin, hat: look?.hat ?? null })
    if (!joined.ok) {
        throw new Error(joined.data?.error ?? 'join_failed')
    }
    token = joined.data.token
    youId = joined.data.id
}

// The stream sends a snapshot, then every event as it happens. The browser reconnects by itself and sends
// the number of the last event it saw, so the server continues from there or sends a new snapshot.
function connect() {
    if (stream) {
        stream.close()
    }
    const source = new EventSource(`/api/stream?token=${encodeURIComponent(token ?? '')}`)
    stream = source
    source.addEventListener('snapshot', (message) => applySnapshot(JSON.parse(message.data)))
    source.addEventListener('event', (message) => applyEvent(JSON.parse(message.data)))
    source.addEventListener('sync', (message) => {
        const sync = JSON.parse(message.data)
        clockOffset = sync.at - Date.now()
    })
    source.addEventListener('error', () => {
        // The browser retries on its own. A token the server no longer knows needs a new join first.
        if (!token) {
            return
        }
        void api('GET', '/api/state').then((result) => {
            if (result.status === 401) {
                token = null
                source.close()
                void start_()
            }
        })
    })
}

let isStarting = false

async function start_() {
    if (isStarting || !look) {
        return
    }
    isStarting = true
    try {
        if (!token) {
            await join()
        }
        connect()
    } catch (error) {
        const code = error instanceof Error ? error.message : ''
        showNotice(ERROR_MESSAGES[code] ?? "Can't reach the club. Trying again…")
        window.setTimeout(() => void start_(), code in ERROR_MESSAGES ? 5000 : RECONNECT_MS)
    } finally {
        isStarting = false
    }
}

/** @param {string} path @param {object} body */
async function act(path, body) {
    if (!token) {
        return
    }
    try {
        const result = await api('POST', path, body)
        if (result.status === 401) {
            token = null
            void start_()
        } else if (!result.ok && result.data?.error) {
            showNotice(ERROR_MESSAGES[result.data.error] ?? 'That did not work. Try again.')
        }
    } catch {
        showNotice("Can't reach the club. Trying again…")
    }
}

function renderOnline() {
    const count = [...hogs.hogs.values()].filter((hog) => !hog.view.npc).length
    const you = youId ? hogs.hogs.get(youId) : null
    const others = count - (you ? 1 : 0)
    $('online').textContent = you
        ? `You are ${you.view.name} · ${others === 1 ? '1 other hog' : `${others} other hogs`} here`
        : `${count} ${count === 1 ? 'hog' : 'hogs'} here`
}

function renderFeed() {
    $('feed').replaceChildren(
        ...feed
            .slice(-6)
            .reverse()
            .map((text) => {
                const item = document.createElement('li')
                item.textContent = text
                return item
            })
    )
}

/** @param {any} next */
function applySnapshot(next) {
    // A server that started again has new phrases, objects, and ids. The page starts over with them.
    if (next.serverId !== world.serverId) {
        window.location.reload()
        return
    }
    const isFirst = objects === null
    clockOffset = next.at - Date.now()
    seenSeq = next.seq
    hogs.sync(next.players, next.at)
    objects = next.objects
    town.setObjects(objects, isFirst)
    feed = next.feed.map((/** @type {{ text: string }} */ entry) => entry.text)
    $('loading').hidden = true
    renderOnline()
    renderFeed()
}

/** @param {any} event */
function applyEvent(event) {
    if (event.seq <= seenSeq) {
        return
    }
    seenSeq = event.seq
    switch (event.kind) {
        case 'join':
            hogs.join({ ...event.player, at: event.at })
            renderOnline()
            break
        case 'leave':
            hogs.remove(event.id)
            renderOnline()
            break
        case 'walk':
            hogs.walk(event.id, { from: event.from, path: event.path, at: event.at })
            break
        case 'say':
            hogs.say(event.id, event.phrase, event.at)
            break
        case 'emote':
            showEmote(event.id, event.emoji)
            if (event.emoji === '🏳️‍🌈') {
                town.rainbow(10)
            }
            break
        case 'poke':
            objects = event.objects
            town.setObjects(objects)
            playPoke(event)
            break
    }
    if (event.text) {
        feed = [...feed, event.text].slice(-20)
        renderFeed()
    }
}

/** @param {{ objectId: string, id: string }} entry */
function playPoke(entry) {
    town.playPoke(entry.objectId)
    hogs.playOnce(entry.id, 'jump')
    if (entry.objectId === 'ship') {
        const launcher = hogs.hogs.get(entry.id)
        const callout = label('callout')
        callout.textContent = `🚀 ${launcher ? launcher.view.name : 'Someone'} shipped!`
        callout.style.zIndex = '2500'
        pin(callout, town.at(34, 15.1, 5.5), 'translate(-50%, -100%)')
        callout.addEventListener('animationend', () => callout.remove())
    }
    if (entry.objectId === 'door-a' || entry.objectId === 'door-b') {
        hogs.hide(entry.id, 0.9)
    }
    if (entry.objectId === 'max') {
        maxSpeaksUntil = performance.now() + 9000
        hogs.playOnce(MAX_ID, 'wave', 12)
    }
}

// ---- Labels that follow things in the town ----------------------------------------------------------------------

const projected = new THREE.Vector3()

/** @param {HTMLElement} element @param {THREE.Vector3} point @param {string} anchor */
function pin(element, point, anchor) {
    projected.copy(point).project(town.camera)
    // A wide label near the side of the stage moves in, so the stage does not cut it off.
    const half = element.offsetWidth / 2 + 6
    const x = Math.min(Math.max(((projected.x + 1) / 2) * stageWidth, half), Math.max(half, stageWidth - half))
    const y = Math.max(((1 - projected.y) / 2) * stageHeight, element.offsetHeight + 6)
    element.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) ${anchor}`
}

/** @param {string} className */
function label(className) {
    const element = document.createElement('div')
    element.className = className
    labels.append(element)
    return element
}

/** @type {Map<string, { tag: HTMLElement, bubble: HTMLElement }>} */
const hogLabels = new Map()
const tip = label('tip')
const maxBubble = label('bubble bubble-max')
tip.hidden = true
maxBubble.hidden = true

/** @param {string} id @param {string} emoji */
function showEmote(id, emoji) {
    const hog = hogs.hogs.get(id)
    if (!hog) {
        return
    }
    const floating = label('emote')
    floating.textContent = emoji
    floating.style.zIndex = '2000'
    pin(floating, town.at(hog.x, hog.y, 3.1), 'translate(-50%, -100%)')
    floating.addEventListener('animationend', () => floating.remove())
    hogs.playOnce(id, 'wave', 14)
}

function updateLabels() {
    for (const [id, entry] of hogLabels) {
        if (!hogs.hogs.has(id)) {
            entry.tag.remove()
            entry.bubble.remove()
            hogLabels.delete(id)
        }
    }
    for (const [id, hog] of hogs.hogs) {
        if (hog.view.npc) {
            continue
        }
        let entry = hogLabels.get(id)
        if (!entry) {
            entry = { tag: label('tag'), bubble: label('bubble') }
            hogLabels.set(id, entry)
        }
        const depth = String(Math.round(hog.y * 10))
        entry.tag.textContent = `${hog.view.client === 'mod' ? '⏳ ' : ''}${hog.view.name}${id === youId ? ' (you)' : ''}`
        entry.tag.classList.toggle('tag-you', id === youId)
        entry.tag.style.zIndex = depth
        pin(entry.tag, town.at(hog.x, hog.y, 0), 'translate(-50%, 0.15em)')
        entry.bubble.hidden = !hog.bubble
        if (hog.bubble) {
            entry.bubble.textContent = hog.bubble
            entry.bubble.style.zIndex = String(1000 + Math.round(hog.y * 10))
            pin(entry.bubble, town.at(hog.x, hog.y, 2.9), 'translate(-50%, -100%) translateY(-0.7em)')
        }
    }

    const max = hogs.hogs.get(MAX_ID)
    const maxSays = objects?.maxSays
    maxBubble.hidden = !(max && maxSays && performance.now() < maxSpeaksUntil)
    if (!maxBubble.hidden) {
        maxBubble.textContent = maxSays
        maxBubble.style.zIndex = '1500'
        pin(maxBubble, town.at(max.x, max.y, 3.4), 'translate(-50%, -100%) translateY(-0.7em)')
    }

    // The tip names the object under the pointer, or the object the player stands next to.
    const you = youId ? hogs.hogs.get(youId) : null
    const near =
        you && !you.moving
            ? world.objects.find(
                  (/** @type {any} */ object) => distanceToFootprint(you.x, you.y, object.footprint) <= world.pokeReach
              )
            : null
    // While Max tells a joke, the joke is the thing to read; the tip for the desk waits.
    const maxIsSpeaking = Boolean(objects?.maxSays) && performance.now() < maxSpeaksUntil
    const wanted = hoveredObject ?? near?.id ?? null
    const shownId = wanted === 'max' && maxIsSpeaking ? null : wanted
    tip.hidden = !shownId
    if (shownId) {
        const object = world.objects.find((/** @type {any} */ candidate) => candidate.id === shownId)
        const heading = document.createElement('b')
        heading.textContent = object.name
        const hint = document.createElement('small')
        hint.textContent = hoveredObject ? `Click: ${object.hint}` : `Press E: ${object.hint}`
        tip.replaceChildren(heading, hint)
        tip.style.zIndex = '3000'
        const anchor = /** @type {any} */ (town.interactables.find((entry) => entry.id === shownId)).label
        pin(tip, anchor, 'translate(-50%, -100%)')
    }

    if (!$('notice').hidden && performance.now() > noticeUntil) {
        $('notice').hidden = true
    }
    $('hint').hidden = hasWalked || !you
    $('hint').textContent = 'Click the snow to walk. Click a building to use it.'
}

/** @param {number} x @param {number} y @param {{ x: number, y: number, w: number, h: number }} rect */
function distanceToFootprint(x, y, rect) {
    return Math.hypot(Math.max(rect.x - x, 0, x - (rect.x + rect.w)), Math.max(rect.y - y, 0, y - (rect.y + rect.h)))
}

// ---- Input -----------------------------------------------------------------------------------------------------

/** @param {MouseEvent} event */
function pickAt(event) {
    const rect = canvas.getBoundingClientRect()
    return town.pick(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        1 - ((event.clientY - rect.top) / rect.height) * 2
    )
}

canvas.addEventListener('pointermove', (event) => {
    const picked = world ? pickAt(event) : null
    hoveredObject = picked && 'objectId' in picked ? picked.objectId : null
})
canvas.addEventListener('pointerleave', () => (hoveredObject = null))

canvas.addEventListener('click', (event) => {
    closePopovers()
    const picked = world && token ? pickAt(event) : null
    if (!picked) {
        return
    }
    hasWalked = true
    if ('objectId' in picked) {
        const object = world.objects.find((/** @type {any} */ candidate) => candidate.id === picked.objectId)
        town.showMarker(object.stand.x, object.stand.y)
        void act('/api/move', { objectId: picked.objectId })
        return
    }
    const bounds = world.walkBounds
    const x = Math.min(Math.max(picked.x, bounds.minX), bounds.maxX)
    const y = Math.min(Math.max(picked.y, bounds.minY), bounds.maxY)
    town.showMarker(x, y)
    void act('/api/move', { x, y })
})

function keyWalk() {
    const you = youId ? hogs.hogs.get(youId) : null
    let dx = 0
    let dy = 0
    for (const key of heldKeys) {
        dx += KEY_DIRECTIONS[key][0]
        dy += KEY_DIRECTIONS[key][1]
    }
    if (!you || (dx === 0 && dy === 0)) {
        return
    }
    const length = Math.hypot(dx, dy)
    hasWalked = true
    lastKeyWalkAt = performance.now()
    void act('/api/move', { x: you.x + (dx / length) * KEY_WALK_REACH, y: you.y + (dy / length) * KEY_WALK_REACH })
}

window.addEventListener('keydown', (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey || !world || !token) {
        return
    }
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key
    if (KEY_DIRECTIONS[key]) {
        event.preventDefault()
        if (!heldKeys.has(key)) {
            heldKeys.add(key)
            keyWalk()
        }
    } else if (key === 'e' && !event.repeat) {
        void act('/api/poke', {})
    } else if (/^[1-9]$/.test(key) && !event.repeat) {
        const phrase = world.phrases[Number(key) - 1]
        if (phrase) {
            void act('/api/say', { phraseId: phrase.id })
        }
    } else if (key === 'Escape') {
        closePopovers()
        if (look) {
            $('card').hidden = true
        }
    }
})

window.addEventListener('keyup', (event) => {
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key
    if (heldKeys.delete(key) && heldKeys.size === 0) {
        // The hedgehog stops a short step ahead, not at the end of the last long step.
        const you = youId ? hogs.hogs.get(youId) : null
        const next = you?.walk.path.find((point) => Math.hypot(point.x - you.x, point.y - you.y) > 0.05)
        if (you && next) {
            const distance = Math.hypot(next.x - you.x, next.y - you.y) || 1
            void act('/api/move', {
                x: you.x + ((next.x - you.x) / distance) * 0.35,
                y: you.y + ((next.y - you.y) / distance) * 0.35,
            })
        }
    }
})
window.addEventListener('blur', () => heldKeys.clear())

// ---- Toolbar, popovers, and the welcome card ----------------------------------------------------------------------

/** @type {Array<[string, string]>} */
const POPOVERS = [
    ['say-toggle', 'phrases'],
    ['help-toggle', 'help'],
]

function closePopovers() {
    for (const [toggle, popover] of POPOVERS) {
        $(popover).hidden = true
        $(toggle).setAttribute('aria-expanded', 'false')
    }
}

function buildToolbar() {
    world.phrases.forEach((/** @type {{ id: string, text: string }} */ phrase, /** @type {number} */ index) => {
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'tool'
        const key = document.createElement('kbd')
        key.textContent = String(index + 1)
        button.append(key, phrase.text)
        button.addEventListener('click', () => {
            closePopovers()
            void act('/api/say', { phraseId: phrase.id })
        })
        $('phrases').append(button)
    })
    world.emotes.forEach((/** @type {{ id: string, emoji: string, label: string }} */ emote) => {
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'tool tool-emote'
        button.textContent = emote.emoji
        button.setAttribute('aria-label', emote.label)
        button.title = emote.label
        button.addEventListener('click', () => void act('/api/emote', { emoteId: emote.id }))
        $('emotes').append(button)
    })
    for (const [toggle, popover] of POPOVERS) {
        $(toggle).addEventListener('click', () => {
            const willOpen = $(popover).hidden
            closePopovers()
            $(popover).hidden = !willOpen
            $(toggle).setAttribute('aria-expanded', String(willOpen))
        })
    }
    $('log-toggle').addEventListener('click', () => {
        $('feed').hidden = !$('feed').hidden
        $('log-toggle').setAttribute('aria-expanded', String(!$('feed').hidden))
    })
    $('me-toggle').addEventListener('click', () => {
        closePopovers()
        $('card-close').hidden = false
        $('card').hidden = false
    })
    $('card-close').addEventListener('click', () => {
        $('card').hidden = true
    })

    const sameLook = (/** @type {any} */ a, /** @type {any} */ b) =>
        Boolean(a && b) && a.skin === b.skin && (a.hat ?? null) === (b.hat ?? null)
    let picked = world.looks.find((/** @type {any} */ candidate) => sameLook(candidate, look)) ?? world.looks[0]
    const buttons = world.looks.map((/** @type {{ skin: string, hat: string | null }} */ candidate) => {
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'skin'
        button.setAttribute('aria-label', candidate.hat ? `${candidate.skin} with ${candidate.hat}` : candidate.skin)
        button.setAttribute('aria-pressed', String(candidate === picked))
        const art = document.createElement('span')
        art.className = 'skin-art'
        const frame = /** @type {any} */ (sprites.animations.get(`skins/${candidate.skin}/idle`))[0]
        art.style.backgroundPosition = `-${frame.x}px -${frame.y}px`
        button.append(art)
        if (candidate.hat) {
            const hat = document.createElement('span')
            hat.className = 'skin-art skin-hat'
            const hatFrame = /** @type {any} */ (sprites.animations.get(`accessories/${candidate.hat}`))[0]
            hat.style.backgroundPosition = `-${hatFrame.x}px -${hatFrame.y}px`
            button.append(hat)
        }
        button.addEventListener('click', () => {
            picked = candidate
            buttons.forEach((/** @type {HTMLElement} */ other) =>
                other.setAttribute('aria-pressed', String(other === button))
            )
        })
        $('skins').append(button)
        return button
    })
    $('enter').addEventListener('click', async () => {
        $('card').hidden = true
        if (token && !sameLook(picked, look)) {
            await api('POST', '/api/leave', {}).catch(() => undefined)
            token = null
        }
        look = { skin: picked.skin, hat: picked.hat ?? null }
        try {
            window.localStorage.setItem(LOOK_KEY, JSON.stringify(look))
        } catch {
            // The choice is kept for this visit only.
        }
        void start_()
    })
}

// ---- Start -------------------------------------------------------------------------------------------------------

let lastFrameAt = performance.now()

/** @param {number} now */
function frame(now) {
    const dt = Math.min(0.1, (now - lastFrameAt) / 1000)
    lastFrameAt = now
    if (heldKeys.size > 0 && now - lastKeyWalkAt > KEY_WALK_MS) {
        keyWalk()
    }
    hogs.update(dt, now / 1000)
    updateLabels()
    town.update(dt, now / 1000)
    window.requestAnimationFrame(frame)
}

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
        $('loading').textContent = "Can't reach the club. Refresh the page to try again."
        return
    }
    world = result.data
    try {
        town = createTown(world, canvas)
    } catch {
        $('loading').textContent = 'This browser cannot draw Hog Town, because WebGL is off.'
        return
    }
    sprites = await loadSprites()
    hogs = createHogs(town, sprites, world, serverNow)
    hogs.add({ id: MAX_ID, npc: true, skin: 'default', hat: 'graduation', x: 35, y: 3.25, facing: 'left', path: [] })

    new ResizeObserver(() => {
        stageWidth = stage.clientWidth
        stageHeight = stage.clientHeight
        town.fitCamera(stageWidth, stageHeight)
    }).observe(stage)

    try {
        const saved = JSON.parse(window.localStorage.getItem(LOOK_KEY) ?? 'null')
        look = world.looks.some(
            (/** @type {any} */ candidate) =>
                candidate.skin === saved?.skin && (candidate.hat ?? null) === (saved?.hat ?? null)
        )
            ? saved
            : null
    } catch {
        look = null
    }
    buildToolbar()
    town.applyNight()
    window.requestAnimationFrame(frame)
    $('card').hidden = look !== null
    if (look) {
        void start_()
    } else {
        // Watching the town while the card is up: a stream without a token.
        connect()
    }
}

void start()
