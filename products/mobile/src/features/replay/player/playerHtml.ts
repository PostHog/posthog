import { inlineScriptSource } from '@/lib/mermaid'

export interface PlayerConfig {
    sessionId: string
    blockCount: number
    seconds: number
    startTimestamp: number | null
    replayProxyToken: string | null
}

export function playerHtml(
    config: PlayerConfig,
    colors: { background: string; ink: string; border: string },
    nonce: string
): string {
    const bundle = require('./player.bundle.json') as string
    const literal = (value: unknown): string => JSON.stringify(value).replace(/</g, '\\u003c')
    return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${nonce}' blob:; style-src 'unsafe-inline' https:; img-src data: blob: https:; font-src data: https:; media-src blob: https:; connect-src 'none'; frame-src 'self' about: blob:; worker-src blob:; base-uri 'none'; form-action 'none'">
<style>
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:${colors.background};color:${colors.ink};font-family:-apple-system,system-ui,sans-serif}
#recording{position:absolute;top:0;left:0;transform-origin:top left;overflow:hidden}.replayer-wrapper{position:relative}iframe{border:0;background:white}
.replayer-mouse{position:absolute;width:16px;height:16px;border:2px solid white;border-radius:50%;background:#555;box-shadow:0 0 2px #000;pointer-events:none}.replayer-mouse-tail{position:absolute;pointer-events:none}
#controls{position:absolute;bottom:0;left:0;right:0;height:72px;padding:8px 12px;border-top:1px solid ${colors.border};background:${colors.background}}
#buttons{display:flex;align-items:center;gap:12px}button,select{font:inherit;color:inherit;background:transparent;border:0;min-height:32px}button{font-weight:600;min-width:56px;text-align:left}#time{flex:1;font-variant-numeric:tabular-nums;font-size:13px}#seek{width:100%;margin:0;height:20px;accent-color:${colors.ink}}
</style></head><body><div id="recording"></div><div id="controls" hidden><input id="seek" type="range" min="0" step="100" value="0" aria-label="Replay position"><div id="buttons"><button id="play">Play</button><span id="time"></span><select id="speed" aria-label="Playback speed"><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option></select></div></div>
<script nonce="${nonce}">window.__mobileReplayConfig=${literal(config)};</script>
<script nonce="${nonce}">${inlineScriptSource(bundle)}</script></body></html>`
}

export type PlayerMessage =
    | { type: 'block'; id: number; index: number }
    | { type: 'ready' }
    | { type: 'error'; reason: string }

export function parsePlayerMessage(data: string, blockCount: number): PlayerMessage | null {
    let value: unknown
    try {
        value = JSON.parse(data)
    } catch {
        return null
    }
    if (!value || typeof value !== 'object') return null
    const message = value as Record<string, unknown>
    if (message.type === 'ready') return { type: 'ready' }
    if (message.type === 'error' && typeof message.reason === 'string') return { type: 'error', reason: message.reason }
    if (
        message.type === 'block' &&
        Number.isSafeInteger(message.id) &&
        Number.isSafeInteger(message.index) &&
        (message.id as number) > 0 &&
        (message.id as number) <= 10000 &&
        (message.index as number) >= 0 &&
        (message.index as number) < blockCount
    ) {
        return { type: 'block', id: message.id as number, index: message.index as number }
    }
    return null
}

export function blockChunkScript(id: number, chunk: string, done: boolean): string {
    return `window.__receiveReplayBlock(${id},${JSON.stringify(chunk).replace(/</g, '\\u003c')},${done});true;`
}
