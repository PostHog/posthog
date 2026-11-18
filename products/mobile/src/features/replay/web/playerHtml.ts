import { inlineScriptSource } from '@/lib/mermaid'

/** The page's origin. It never resolves, so the page can reach nothing on it; `'self'` in the CSP means only this. */
export const PLAYER_ORIGIN = 'https://replay-player.invalid/'

let bundle: string | null = null

// Metro exports the built player as a string (metro.transformer.js). `node common/replay-headless/build-phone.mjs` writes it.
function playerBundle(): string {
    bundle ??= inlineScriptSource(require('./phonePlayer.generated.replay') as string)
    return bundle
}

/**
 * Recorded pages are untrusted. rrweb rebuilds them in an iframe sandboxed without `allow-scripts`, and this policy
 * lets only the player's own script run and stops the page from making any request except images, styles and fonts.
 */
export function playerHtml(nonce: string): string {
    const csp = [
        "default-src 'none'",
        `script-src 'nonce-${nonce}'`,
        "style-src 'unsafe-inline' https: data:",
        'img-src https: data: blob:',
        'font-src https: data:',
        'media-src https: data: blob:',
        "connect-src 'none'",
        "frame-src 'self' about: blob:",
        'worker-src blob:',
        "base-uri 'none'",
        "form-action 'none'",
    ].join('; ')
    return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<style>
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}
#content{position:absolute;top:0;left:0}
.replayer-wrapper{position:relative}
iframe{border:0;background:#fff}
.replayer-mouse{position:absolute;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;background:rgba(29,74,255,.45);border:2px solid #fff;box-shadow:0 0 3px rgba(0,0,0,.4);pointer-events:none;transition:left .05s linear,top .05s linear}
.replayer-mouse.active{background:rgba(245,78,0,.7)}
.replayer-mouse-tail{display:none}
</style></head><body><div id="content"></div>
<script nonce="${nonce}">${playerBundle()}</script></body></html>`
}
