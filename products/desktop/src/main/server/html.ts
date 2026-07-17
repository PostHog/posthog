/**
 * Generates the index.html served by the local backend.
 *
 * The frontend build (`pnpm --filter=@posthog/frontend build`) emits a `dist/index.html`
 * that is still a Django template (it `{% include %}`s head.html for the app context and
 * asset URLs). The desktop app has no Django, so we generate an equivalent document here:
 * same chunk loader contract (`window.ESBUILD_LOAD_SCRIPT` / `window.ESBUILD_LOAD_CHUNKS`),
 * assets resolved from `dist/preload-manifest.json`, and crucially NO
 * `window.POSTHOG_APP_CONTEXT` — when the context global is absent, `preflightLogic` and
 * `userLogic` fetch `/_preflight/` and `/api/users/@me/` themselves, which the local
 * backend proxies to the configured PostHog Cloud region.
 */

export interface PreloadManifest {
    /** e.g. "static/index-ABC123.css" */
    css: string
    /** e.g. "static/Inter-ABC123.woff2" */
    font: string
    /** Entry JS first, then the chunks it imports, e.g. ["static/index-ABC123.js", ...] */
    js: string[]
    authenticatedJs: string[]
}

// Mirrors the pre-React shell styles in frontend/src/index.html, so boot looks identical.
const CRITICAL_CSS = `
html,body,#root{height:100%;margin:0;padding:0}
*,:after,:before{box-sizing:border-box}
#root:empty,.Preloader{background:#f3f4ef;color:#111;font-family:Inter,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica Neue,Arial,sans-serif;font-size:14px;line-height:1.4}
[data-boot-theme=dark] #root:empty,[data-boot-theme=dark] .Preloader{background:#1d1f27;color:#fff}
@media (prefers-color-scheme:dark){[data-boot-theme=system] #root:empty,[data-boot-theme=system] .Preloader{background:#1d1f27;color:#fff}}
.Preloader{display:flex;align-items:center;justify-content:center;height:100%;min-height:200px;width:100%}
.Preloader__inner{width:25px;height:25px;border:5px solid rgba(245,78,0,.333);border-top-color:#f54e00;border-radius:50%;animation:preloader-spin 1s linear infinite}
.Preloader button{border:0;padding:0;background:none;font:inherit;color:inherit;text-decoration:underline;cursor:pointer}
@keyframes preloader-spin{to{transform:rotate(360deg)}}
`.trim()

function escapeForScript(value: string): string {
    return JSON.stringify(value)
}

export interface BuildIndexHtmlOptions {
    /** Desktop app version, exposed to the frontend as window.__POSTHOG_DESKTOP__ */
    desktopVersion?: string
    /** Node process.platform of the main process, e.g. "darwin" — the frontend uses it to reserve space for macOS traffic lights */
    desktopPlatform?: string
}

export function buildIndexHtml(manifest: PreloadManifest, options: BuildIndexHtmlOptions = {}): string {
    const jsEntry = manifest.js[0] ? manifest.js[0].replace(/^static\//, '') : 'index.js'
    const cssEntry = manifest.css ? manifest.css.replace(/^static\//, '') : 'index.css'

    const preloadLinks: string[] = []
    if (manifest.font) {
        preloadLinks.push(`<link rel="preload" href="/${manifest.font}" as="font" type="font/woff2" crossorigin>`)
    }
    if (manifest.css) {
        preloadLinks.push(`<link rel="preload" href="/${manifest.css}" as="style" crossorigin="anonymous">`)
    }
    for (const url of [...manifest.js, ...manifest.authenticatedJs]) {
        preloadLinks.push(`<link rel="modulepreload" href="/${url}">`)
    }

    // Same loader contract as common/esbuilder/utils.mjs `copyIndexHtml`, minus the
    // per-scene chunk map (which only exists inside the Django-rendered index.html).
    // sceneLogic calls ESBUILD_LOAD_CHUNKS optionally, so an empty map just means scenes
    // fall back to cascading dynamic imports - correct, marginally slower on first visit.
    const loaderScript = `
window.__POSTHOG_DESKTOP__ = { version: ${escapeForScript(options.desktopVersion || '0.0.0')}, platform: ${escapeForScript(options.desktopPlatform || '')} }
window.JS_URL = ''
window.ESBUILD_LOADED_CHUNKS = new Set()
window.ESBUILD_LOAD_CHUNKS = function (name) {}
window.ESBUILD_LOAD_SCRIPT = async function (file) {
    try {
        await import('/static/' + file)
    } catch (error) {
        console.error('Error loading chunk: "' + file + '"', error)
        if (file === ${escapeForScript(jsEntry)} && file !== 'index.js') {
            await import('/static/index.js')
        }
    }
}
document.head.insertAdjacentHTML('beforeend', '<link rel="stylesheet" href="/static/' + ${escapeForScript(cssEntry)} + '" crossorigin="anonymous">')
window.ESBUILD_LOAD_SCRIPT(${escapeForScript(jsEntry)})
`.trim()

    return `<!doctype html>
<html lang="en" data-boot-theme="system">
    <head>
        <meta charset="utf-8">
        <title>PostHog</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="icon" type="image/png" sizes="32x32" href="/static/icons/favicon-32x32.png">
        <style>${CRITICAL_CSS}</style>
        ${preloadLinks.join('\n        ')}
        <script>${loaderScript}</script>
    </head>
    <body>
        <div id="root"></div>
    </body>
</html>
`
}
