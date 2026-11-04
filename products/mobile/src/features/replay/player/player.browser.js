import { CorsPlugin, createCorsPlugin } from '@posthog/replay-shared'
import { HostBridge } from '../../../../../../common/replay-headless/src/host-bridge'
import { createReplayers } from '../../../../../../common/replay-headless/src/replayer-factory'
import { ViewportScaler } from '../../../../../../common/replay-headless/src/viewport-scaler'
import { ReplayBlockBridge, replayWindowAt } from './playerRuntime'

const config = window.__mobileReplayConfig
const post = (message) => window.ReactNativeWebView.postMessage(JSON.stringify(message))
const blocks = new ReplayBlockBridge(post)

window.__receiveReplayBlock = (id, text, done) => blocks.receive(id, text, done)
window.__setReplayBlockLoading = (id, loading) => blocks.setLoading(id, loading)
window.__cancelReplayBlocks = () => blocks.cancel()
window.fetch = (url) => blocks.request(String(url))
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
        blocks.cancel()
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
    const ownerAt = (ts) => replayWindowAt(windows, segments, ts)
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
init().catch(() => {
    blocks.cancel()
    post({ type: 'error', reason: 'render_failed' })
})
