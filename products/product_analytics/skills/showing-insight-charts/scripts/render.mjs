import { readFileSync } from 'node:fs'
import { chromium } from 'playwright'

const spec = JSON.parse(readFileSync(0, 'utf8'))
const browser = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch())
const page = await browser.newPage({
    viewport: { width: 1000, height: 600 },
    deviceScaleFactor: 2,
    reducedMotion: 'reduce',
})
await page.setContent(`<style>
    body { margin: 0; background: #fff; font-family: -apple-system, BlinkMacSystemFont, Inter, 'Segoe UI', sans-serif; color: #111827; }
    #root { padding: 24px 28px; }
    .subtitle { font-size: 12px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: #6b7280; }
    h1 { font-size: 20px; margin: 6px 0 16px; }
    .chart { height: 420px; }
    /* The Tailwind classes that quill-charts uses. The npm package ships no CSS. */
    .flex { display: flex; } .inline-flex { display: inline-flex; } .inline-block { display: inline-block; }
    .flex-col { flex-direction: column; } .flex-row { flex-direction: row; } .flex-wrap { flex-wrap: wrap; }
    .flex-1 { flex: 1 1 0%; } .flex-none { flex: none; } .shrink-0 { flex-shrink: 0; }
    .min-w-0 { min-width: 0; } .min-h-0 { min-height: 0; } .self-stretch { align-self: stretch; }
    .items-center { align-items: center; } .justify-center { justify-content: center; }
    .gap-x-3 { column-gap: 12px; } .gap-y-1 { row-gap: 4px; } .gap-1\\.5 { gap: 6px; }
    .text-xs { font-size: 12px; } .leading-none { line-height: 1; }
    .w-2\\.5 { width: 10px; } .h-2\\.5 { height: 10px; } .rounded-sm { border-radius: 2px; }
    .truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style><div id="root"></div>`)
await page.evaluate((s) => (window.SPEC = s), spec)
await page.addScriptTag({ path: new URL('bundle.js', import.meta.url).pathname })
await page.waitForSelector('canvas')
await page.waitForTimeout(300)
await page.locator('#root').screenshot({ path: process.argv[2] })
await browser.close()
console.info(process.argv[2])
