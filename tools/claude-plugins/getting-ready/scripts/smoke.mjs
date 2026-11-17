import { writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'

const [baseUrl, stateDir] = process.argv.slice(2)
const require = createRequire(join(process.cwd(), 'package.json'))
const { chromium } = require('playwright')

const browser = await chromium.launch()
try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })
    const page = await context.newPage()
    await page.goto(`${baseUrl}/login`)

    // Both calls run in-page so Django's CSRF middleware sees the page's cookies.
    const workspace = await page.evaluate(async () => {
        const r = await fetch('/api/setup_test/organization_with_team/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ skip_onboarding: true, use_current_time: true }),
        })
        const text = await r.text()
        if (!r.ok) {
            throw new Error(`setup_test returned ${r.status}: ${text.slice(0, 500)}`)
        }
        return JSON.parse(text).result
    })

    const loginStatus = await page.evaluate(async (email) => {
        const r = await fetch('/api/login/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password: '12345678' }),
        })
        return r.status
    }, workspace.user_email)
    if (loginStatus !== 200) {
        throw new Error(`login returned ${loginStatus}`)
    }

    await page.goto(`${baseUrl}/project/${workspace.team_id}/home`)
    // networkidle never settles here because posthog-js and Vite HMR keep polling.
    await page.locator('[data-attr]').first().waitFor({ timeout: 120_000 })
    await page.waitForTimeout(2000)
    await page.screenshot({ path: join(stateDir, 'smoke.png') })

    await context.storageState({ path: join(stateDir, 'storage-state.json') })
    writeFileSync(
        join(stateDir, 'workspace.json'),
        JSON.stringify({ ...workspace, password: '12345678', base_url: baseUrl }, null, 2)
    )
    console.log(JSON.stringify({ team_id: workspace.team_id, user_email: workspace.user_email }))
} finally {
    await browser.close()
}
