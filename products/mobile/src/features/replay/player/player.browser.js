import { CorsPlugin, createCorsPlugin } from '@posthog/replay-shared'
import { HostBridge } from '../../../../../../common/replay-headless/src/host-bridge'
import { createReplayers } from '../../../../../../common/replay-headless/src/replayer-factory'
import { ViewportScaler } from '../../../../../../common/replay-headless/src/viewport-scaler'

const config = window.__mobileReplayConfig
const pending = new Map()
let nextRequest = 0
const post = (message) => window.ReactNativeWebView.postMessage(JSON.stringify(message))

window.__receiveReplayBlock = (id, text, done) => {
    const request = pending.get(id)
    if (!request) return
    request.parts.push(text)
    if (done) {
        pending.delete(id)
        request.resolve(new Response(request.parts.join('')))
    }
}
window.fetch = (url) => {
    const match = /^\/__blocks\/(\d+)$/.exec(String(url))
    if (!match) return Promise.reject(new Error('Unsupported replay request'))
    const id = ++nextRequest
    return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject, parts: [] })
        post({ type: 'block', id, index: Number(match[1]) })
    })
}
window.__posthog_player_emit__ = async (message) => {
    if (message.type === 'loading_progress') post({ type: 'progress', loaded: message.loaded, total: message.total })
}

function clock(ms) {
    const total = Math.floor(Math.max(0, ms) / 1000)
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

async function init() {
    Object.assign(
        CorsPlugin,
        createCorsPlugin(() => config.replayProxyToken)
    )
    const root = document.getElementById('recording')
    const setup = await createReplayers(
        { teamId: 0, sessionId: config.sessionId, blockCount: config.blockCount, playbackSpeed: 1, mouseTail: false },
        root,
        new HostBridge()
    )
    if (typeof setup === 'string') {
        post({ type: 'error', reason: setup })
        return
    }
    const { windows, segments, firstTimestamp } = setup
    const duration = Math.max(...windows.map((tab) => tab.lastTimestamp)) - firstTimestamp
    let offset = Math.max(
        0,
        Math.min(duration, (config.startTimestamp ?? firstTimestamp) + config.seconds * 1000 - firstTimestamp)
    )
    let anchor = performance.now()
    let playing = false
    let speed = 1
    let active = null
    const scaler = new ViewportScaler(root, 72)
    const play = document.getElementById('play')
    const seek = document.getElementById('seek')
    const time = document.getElementById('time')
    const speeds = document.getElementById('speed')
    seek.max = String(duration)
    const position = () => Math.min(duration, offset + (playing ? (performance.now() - anchor) * speed : 0))
    const ownerAt = (ts) => {
        const segment =
            segments.find((seg) => seg.isActive && ts >= seg.startTimestamp && ts <= seg.endTimestamp) ??
            segments.find((seg) => ts >= seg.startTimestamp && ts <= seg.endTimestamp)
        return (
            windows.find((tab) => tab.windowId === segment?.windowId) ??
            windows.find((tab) => ts >= tab.firstTimestamp && ts <= tab.lastTimestamp) ??
            windows[windows.length - 1]
        )
    }
    const draw = () => {
        const ts = firstTimestamp + offset
        const tab = ownerAt(ts)
        for (const item of windows) {
            item.replayer.pause()
            item.root.style.visibility = item === tab ? 'visible' : 'hidden'
        }
        active = tab
        const local = Math.max(0, ts - tab.firstTimestamp)
        if (playing) tab.replayer.play(local)
        else tab.replayer.pause(local)
        scaler.fitReplayer(tab.replayer)
    }
    const update = () => {
        seek.value = String(position())
        time.textContent = `${clock(position())} / ${clock(duration)}`
        play.textContent = playing ? 'Pause' : 'Play'
        play.setAttribute('aria-label', playing ? 'Pause replay' : 'Play replay')
    }
    const pause = () => {
        offset = position()
        playing = false
        draw()
        update()
    }
    window.__pauseReplay = pause
    play.onclick = () => {
        offset = position() >= duration ? 0 : position()
        playing = !playing
        anchor = performance.now()
        draw()
        update()
    }
    seek.oninput = () => {
        offset = Number(seek.value)
        anchor = performance.now()
        draw()
        update()
    }
    speeds.onchange = () => {
        offset = position()
        speed = Number(speeds.value)
        anchor = performance.now()
        for (const tab of windows) tab.replayer.setConfig({ speed })
        draw()
    }
    for (const tab of windows) scaler.attachToReplayer(tab.replayer, () => active === tab)
    window.addEventListener('resize', () => scaler.fitReplayer(active.replayer))
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) pause()
    })
    function tick() {
        if (playing) {
            const current = position()
            if (current >= duration) pause()
            else if (ownerAt(firstTimestamp + current) !== active) {
                offset = current
                anchor = performance.now()
                draw()
            }
            update()
        }
        requestAnimationFrame(tick)
    }
    draw()
    update()
    requestAnimationFrame(tick)
    document.getElementById('controls').hidden = false
    post({ type: 'ready' })
}
init().catch(() => post({ type: 'error', reason: 'render_failed' }))
