// The browser client for Club Hoguin. It polls the room state, draws Hog Town, and sends what the player does.
import { createHogs, loadSprites } from '/hogs.js'
import { THREE } from '/kit.js'
import { createTown } from '/town.js'

const POLL_MOVING_MS = 100
const POLL_QUIET_MS = 350
const KEY_WALK_MS = 120
const KEY_WALK_REACH = 2.5
const MAX_ID = 'npc-max'
const SKIN_KEY = 'club-hoguin-skin'

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
/** @type {string | null} */
let skin = null
/** @type {any} */
let snapshot = null
/** @type {number | null} */
let lastFeedId = null
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

// ---- Talking to the server -----------------------------------------------------------------------------------------

let pollTimer = 0
let isPolling = false
let pollAgain = false

async function poll() {
    if (isPolling) {
        pollAgain = true
        return
    }
    isPolling = true
    window.clearTimeout(pollTimer)
    let delay = POLL_QUIET_MS
    try {
        if (!token && skin) {
            const joined = await api('POST', '/api/join', { client: clientKind, skin })
            if (!joined.ok) {
                throw new Error(joined.data?.error ?? 'join_failed')
            }
            token = joined.data.token
        }
        const result = await api('GET', '/api/state')
        if (result.status === 401) {
            token = null
            delay = 0
        } else if (result.ok) {
            applySnapshot(result.data)
            if (result.data.players.some((/** @type {any} */ player) => player.moving)) {
                delay = POLL_MOVING_MS
            }
        }
    } catch (error) {
        const code = error instanceof Error ? error.message : ''
        showNotice(ERROR_MESSAGES[code] ?? "Can't reach the club. Trying again…")
        delay = 2000
    }
    isPolling = false
    if (pollAgain) {
        pollAgain = false
        delay = 0
    }
    pollTimer = window.setTimeout(poll, delay)
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
    void poll()
}

/** @param {any} next */
function applySnapshot(next) {
    const isFirst = snapshot === null
    snapshot = next
    hogs.sync(next.players)
    town.setObjects(next.objects, isFirst)
    $('loading').hidden = true
    if (next.you) {
        const others = next.online - 1
        $('online').textContent =
            `You are ${next.you.name} · ${others === 1 ? '1 other hog' : `${others} other hogs`} here`
    } else {
        $('online').textContent = `${next.online} ${next.online === 1 ? 'hog' : 'hogs'} here`
    }

    const newest = next.feed.length > 0 ? next.feed[next.feed.length - 1].id : 0
    if (lastFeedId !== null) {
        for (const entry of next.feed) {
            if (entry.id > lastFeedId && entry.kind === 'poke') {
                playPoke(entry)
            }
        }
    }
    if (newest !== lastFeedId) {
        lastFeedId = newest
        $('feed').replaceChildren(
            ...next.feed
                .slice(-6)
                .reverse()
                .map((/** @type {{ text: string }} */ entry) => {
                    const item = document.createElement('li')
                    item.textContent = entry.text
                    return item
                })
        )
    }
}

/** @param {{ objectId: string, playerId: string }} entry */
function playPoke(entry) {
    town.playPoke(entry.objectId)
    hogs.playOnce(entry.playerId, 'jump')
    if (entry.objectId === 'door-a' || entry.objectId === 'door-b') {
        hogs.hide(entry.playerId, 0.9)
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

/** @type {Map<string, { tag: HTMLElement, bubble: HTMLElement, emoteSeq: number }>} */
const hogLabels = new Map()
const tip = label('tip')
const maxBubble = label('bubble bubble-max')
tip.hidden = true
maxBubble.hidden = true

function updateLabels() {
    const youId = snapshot?.you?.id
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
            entry = { tag: label('tag'), bubble: label('bubble'), emoteSeq: 0 }
            hogLabels.set(id, entry)
        }
        const depth = String(Math.round(hog.y * 10))
        entry.tag.textContent = `${hog.view.client === 'mod' ? '⏳ ' : ''}${hog.view.name}${id === youId ? ' (you)' : ''}`
        entry.tag.classList.toggle('tag-you', id === youId)
        entry.tag.style.zIndex = depth
        pin(entry.tag, town.at(hog.x, hog.y, 0), 'translate(-50%, 0.15em)')
        entry.bubble.hidden = !hog.view.bubble
        if (hog.view.bubble) {
            entry.bubble.textContent = hog.view.bubble
            entry.bubble.style.zIndex = String(1000 + Math.round(hog.y * 10))
            pin(entry.bubble, town.at(hog.x, hog.y, 2.9), 'translate(-50%, -100%) translateY(-0.7em)')
        }
        const emote = hog.view.emote
        if (emote && emote.seq !== entry.emoteSeq) {
            entry.emoteSeq = emote.seq
            const floating = label('emote')
            floating.textContent = emote.emoji
            floating.style.zIndex = '2000'
            pin(floating, town.at(hog.x, hog.y, 3.1), 'translate(-50%, -100%)')
            floating.addEventListener('animationend', () => floating.remove())
            hogs.playOnce(id, 'wave', 14)
        }
    }

    const max = hogs.hogs.get(MAX_ID)
    const maxSays = snapshot?.objects.maxSays
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
    const shownId = hoveredObject ?? near?.id ?? null
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
    const you = snapshot?.you ? hogs.hogs.get(snapshot.you.id) : null
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
    }
})

window.addEventListener('keyup', (event) => {
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key
    if (heldKeys.delete(key) && heldKeys.size === 0) {
        // The hedgehog stops a short step ahead, not at the end of the last long step.
        const you = snapshot?.you ? hogs.hogs.get(snapshot.you.id) : null
        const next = you?.path[0]
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
        $('card').hidden = false
    })

    let picked = skin ?? world.skins[0]
    const buttons = world.skins.map((/** @type {string} */ name) => {
        const button = document.createElement('button')
        button.type = 'button'
        button.className = 'skin'
        button.setAttribute('aria-label', name)
        button.setAttribute('aria-pressed', String(name === picked))
        const art = document.createElement('span')
        art.className = 'skin-art'
        const frame = /** @type {any} */ (sprites.animations.get(`skins/${name}/idle`))[0]
        art.style.backgroundPosition = `-${frame.x}px -${frame.y}px`
        button.append(art)
        button.addEventListener('click', () => {
            picked = name
            buttons.forEach((/** @type {HTMLElement} */ other) =>
                other.setAttribute('aria-pressed', String(other === button))
            )
        })
        $('skins').append(button)
        return button
    })
    $('enter').addEventListener('click', async () => {
        $('card').hidden = true
        if (token && picked !== skin) {
            await api('POST', '/api/leave', {}).catch(() => undefined)
            token = null
        }
        skin = picked
        try {
            window.localStorage.setItem(SKIN_KEY, picked)
        } catch {
            // The choice is kept for this visit only.
        }
        void poll()
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
    hogs = createHogs(town, sprites, world)
    hogs.add({ id: MAX_ID, npc: true, skin: 'default', hat: 'graduation', x: 35, y: 3.25, facing: 'left', path: [] })

    new ResizeObserver(() => {
        stageWidth = stage.clientWidth
        stageHeight = stage.clientHeight
        town.fitCamera(stageWidth, stageHeight)
    }).observe(stage)

    try {
        const saved = window.localStorage.getItem(SKIN_KEY)
        skin = world.skins.includes(saved) ? saved : null
    } catch {
        skin = null
    }
    buildToolbar()
    town.applyNight()
    window.requestAnimationFrame(frame)
    $('card').hidden = skin !== null
    void poll()
}

void start()
