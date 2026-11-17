import { PlaywrightSetup } from '@playwright-utils/playwright-setup'
import { expect, test } from '@playwright-utils/workspace-test-base'
import { Page } from '@playwright/test'

const RECIPIENT = 'reader@example.com'
const UPDATE_URL = '**/messaging-preferences/update*'

interface PreferencesPage {
    path: string
    productNewsId: string
    eventInvitesId: string
    storedPreferences: (categoryKey?: string) => Promise<Record<string, string> | undefined>
}

function responseGate(): { opened: Promise<void>; open: () => void } {
    let open = (): void => {}
    const opened = new Promise<void>((resolve) => {
        open = resolve
    })
    return { opened, open }
}

async function createPreferencesPage(page: Page, playwrightSetup: PlaywrightSetup): Promise<PreferencesPage> {
    const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    const api = `/api/projects/${workspace.team_id}`
    const headers = { Authorization: `Bearer ${workspace.personal_api_key}` }

    const categoryIds: string[] = []
    for (const [key, name] of [
        ['product_news', 'Product news'],
        ['event_invites', 'Event invites'],
    ]) {
        const response = await page.request.post(`${api}/messaging_categories/`, {
            headers,
            data: { key, name, public_description: `Emails about ${name.toLowerCase()}.` },
        })
        expect(response.ok()).toBe(true)
        categoryIds.push((await response.json()).id)
    }

    // A personal API key can't mint a preferences link, so the workspace user signs in for it
    await playwrightSetup.login(page, workspace)
    const csrfToken = (await page.context().cookies()).find((cookie) => cookie.name === 'posthog_csrftoken')?.value
    expect(csrfToken).toBeTruthy()
    const linkResponse = await page.request.post(`${api}/messaging_preferences/generate_link/`, {
        headers: { 'X-CSRFToken': decodeURIComponent(csrfToken ?? '') },
        data: { recipient: RECIPIENT },
    })
    expect(linkResponse.ok()).toBe(true)
    const path = new URL((await linkResponse.json()).preferences_url).pathname

    // The opt-out lists are the API's read of what the page stored for the recipient
    const storedPreferences = async (categoryKey?: string): Promise<Record<string, string> | undefined> => {
        const response = await page.request.get(`${api}/messaging_preferences/opt_outs/`, {
            headers,
            params: { search: RECIPIENT, ...(categoryKey ? { category_key: categoryKey } : {}) },
        })
        expect(response.ok()).toBe(true)
        return (await response.json()).results[0]?.preferences
    }

    return { path, productNewsId: categoryIds[0], eventInvitesId: categoryIds[1], storedPreferences }
}

test.describe('Message preferences page', () => {
    test('all marketing off holds topics off, and turning it back on restores them', async ({
        browser,
        page,
        playwrightSetup,
    }) => {
        const { path, productNewsId, eventInvitesId, storedPreferences } = await createPreferencesPage(
            page,
            playwrightSetup
        )
        const recipientContext = await browser.newContext({ storageState: { cookies: [], origins: [] } })
        const recipientPage = await recipientContext.newPage()
        const productNews = recipientPage.getByRole('checkbox', { name: 'Product news' })
        const eventInvites = recipientPage.getByRole('checkbox', { name: 'Event invites' })
        const allMarketing = recipientPage.getByRole('checkbox', { name: 'All marketing communications' })
        const successToast = recipientPage.getByText('Preferences updated successfully')
        const isPageRead = (url: URL): boolean => url.pathname === path
        const status = (id: string): ReturnType<Page['getByTestId']> => recipientPage.getByTestId(`status-${id}`)

        try {
            await recipientPage.goto(path)

            await test.step('a recipient keeps product news and turns event invites off', async () => {
                await eventInvites.click()
                await expect(status(eventInvitesId)).toHaveText('Not subscribed')
                await expect(productNews).toBeChecked()
            })

            await test.step('all marketing off shows every topic off and leaves the topic choices stored', async () => {
                await allMarketing.click()
                await expect(status('$all')).toHaveText('Not subscribed')
                for (const [topic, id] of [
                    [productNews, productNewsId],
                    [eventInvites, eventInvitesId],
                ] as const) {
                    await expect(status(id)).toHaveText('Not subscribed')
                    await expect(topic).not.toBeChecked()
                    await expect(topic).toBeDisabled()
                }
                expect(await storedPreferences()).toEqual({
                    $all: 'OPTED_OUT',
                    [productNewsId]: 'OPTED_IN',
                    [eventInvitesId]: 'OPTED_OUT',
                })
            })

            await test.step('a reload keeps all marketing off', async () => {
                await recipientPage.reload()
                await expect(allMarketing).not.toBeChecked()
                await expect(productNews).toBeDisabled()
                await expect(productNews).not.toBeChecked()
            })

            await test.step('all marketing on restores each topic to its saved choice', async () => {
                await allMarketing.click()
                await expect(status('$all')).toHaveText('Subscribed')
                await expect(productNews).toBeChecked()
                await expect(productNews).toBeEnabled()
                await expect(eventInvites).not.toBeChecked()
                await expect(eventInvites).toBeEnabled()
                expect(await storedPreferences('event_invites')).toEqual({
                    $all: 'OPTED_IN',
                    [productNewsId]: 'OPTED_IN',
                    [eventInvitesId]: 'OPTED_OUT',
                })
            })

            await test.step('a failed save turns the clicked topic back', async () => {
                await recipientPage.route(
                    UPDATE_URL,
                    (route) => route.fulfill({ status: 500, json: { error: 'Something went wrong' } }),
                    { times: 1 }
                )
                await productNews.click()
                await expect(recipientPage.getByText('Something went wrong')).toBeVisible()
                await expect(status(productNewsId)).toHaveText('Subscribed')
                await expect(productNews).toBeChecked()
            })

            await test.step('saves that answer out of commit order leave the page showing what was stored', async () => {
                const committed = responseGate()
                const answer = responseGate()
                await recipientPage.route(
                    UPDATE_URL,
                    async (route) => {
                        const response = await route.fetch()
                        committed.open()
                        await answer.opened
                        await route.fulfill({ response })
                    },
                    { times: 1 }
                )
                await expect(successToast).toHaveCount(0)
                await allMarketing.click()
                await committed.opened
                await expect(status(productNewsId)).toHaveText('Saving…')
                await allMarketing.click()
                await expect(successToast).toBeVisible()
                answer.open()

                await expect(status('$all')).toHaveText('Subscribed')
                await expect(status(productNewsId)).toHaveText('Subscribed')
                await expect(allMarketing).toBeChecked()
                await expect(productNews).toBeChecked()
                await expect(eventInvites).not.toBeChecked()
                expect(await storedPreferences('event_invites')).toEqual({
                    $all: 'OPTED_IN',
                    [productNewsId]: 'OPTED_IN',
                    [eventInvitesId]: 'OPTED_OUT',
                })
            })

            await test.step('a read-back that answers after a later save does not undo it', async () => {
                const read = responseGate()
                const answer = responseGate()
                await recipientPage.route(
                    isPageRead,
                    async (route) => {
                        const response = await route.fetch()
                        read.open()
                        await answer.opened
                        await route.fulfill({ response })
                    },
                    { times: 1 }
                )
                await eventInvites.click()
                await read.opened
                await eventInvites.click()
                await expect(status(eventInvitesId)).toHaveText('Not subscribed')

                // The page renders once it has handled the late read, so the checks below see its outcome
                await recipientPage.evaluate((label) => {
                    const target = document.querySelector(`[data-attr="${label}"]`) as Node
                    ;(window as unknown as { nextRender: Promise<void> }).nextRender = new Promise((resolve) =>
                        new MutationObserver((_, observer) => {
                            observer.disconnect()
                            resolve()
                        }).observe(target, { childList: true })
                    )
                }, `status-${eventInvitesId}`)
                answer.open()
                await recipientPage.evaluate(() => (window as unknown as { nextRender: Promise<void> }).nextRender)
                await expect(status(eventInvitesId)).toHaveText('Not subscribed')
                await expect(eventInvites).not.toBeChecked()
                expect(await storedPreferences('event_invites')).toEqual({
                    $all: 'OPTED_IN',
                    [productNewsId]: 'OPTED_IN',
                    [eventInvitesId]: 'OPTED_OUT',
                })
            })

            await test.step('a read-back without the preferences form keeps the saved choice and asks for a reload', async () => {
                await recipientPage.route(
                    isPageRead,
                    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<p>Another page</p>' }),
                    { times: 1 }
                )
                await expect(successToast).toHaveCount(0)
                await productNews.click()
                const messages = recipientPage.getByRole('status')
                const saved = messages.getByText('Preferences updated successfully')
                const unconfirmed = messages.getByText("Couldn't confirm your preferences.", { exact: false })
                await expect(saved).toBeVisible()
                await expect(unconfirmed).toBeVisible()
                const [savedBox, unconfirmedBox] = await Promise.all([saved.boundingBox(), unconfirmed.boundingBox()])
                expect(unconfirmedBox!.y).toBeGreaterThanOrEqual(savedBox!.y + savedBox!.height)

                // Stacked messages can cover a switch while they show, so a click there must still reach it.
                // A shorter window lets the page scroll a switch under them.
                await recipientPage.setViewportSize({ width: 1280, height: 400 })
                await eventInvites.evaluate(
                    (toggle, top) => window.scrollBy(0, toggle.getBoundingClientRect().top - top),
                    unconfirmedBox!.y + 8
                )
                const switchUnderMessages = (): Promise<string> =>
                    eventInvites.evaluate((toggle) => {
                        const box = toggle.getBoundingClientRect()
                        const [x, y] = [box.x + box.width / 2, box.y + box.height / 2]
                        const covered = Array.from(document.querySelectorAll('#toasts > *')).some((toast) => {
                            const area = toast.getBoundingClientRect()
                            return x >= area.left && x <= area.right && y >= area.top && y <= area.bottom
                        })
                        if (!covered) {
                            return 'not covered'
                        }
                        return document.elementFromPoint(x, y) === toggle ? 'clickable' : 'blocked'
                    })
                // A message slides in, so it covers the switch only once it settles
                await expect.poll(switchUnderMessages).not.toBe('not covered')
                expect(await switchUnderMessages()).toBe('clickable')
                await expect(status(productNewsId)).toHaveText('Not subscribed')
                await expect(productNews).not.toBeChecked()
                expect(await storedPreferences('product_news')).toEqual({
                    $all: 'OPTED_IN',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_OUT',
                })
            })
        } finally {
            await recipientContext.close()
        }
    })
})
