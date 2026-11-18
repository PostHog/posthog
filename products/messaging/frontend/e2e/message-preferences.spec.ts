import { PlaywrightSetup } from '@playwright-utils/playwright-setup'
import { expect, test } from '@playwright-utils/workspace-test-base'
import { Page, Route } from '@playwright/test'

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

    // Recipients see the tracking switch once the workspace asks for their consent
    const consentResponse = await page.request.patch(`/api/environments/${workspace.team_id}/`, {
        headers,
        data: { workflows_config: { email_tracking_consent_mode: 'opt_out' } },
    })
    expect(consentResponse.ok()).toBe(true)

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
        const tracking = recipientPage.getByRole('checkbox', { name: 'Open and click tracking' })
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
                // Messages leave on a timer, so a paused clock keeps them on screen for the checks below
                await recipientPage.clock.install()
                await recipientPage.clock.pauseAt(Date.now() + 1000)
                await productNews.click()
                const messages = recipientPage.getByRole('status')
                const saved = messages.getByText('Preferences updated successfully')
                const unconfirmed = messages.getByText("Couldn't confirm your preferences.", { exact: false })
                await expect(saved).toBeVisible()
                await expect(unconfirmed).toBeVisible()
                // Messages slide in on the next animation frame
                await recipientPage.clock.runFor(100)
                const [savedBox, unconfirmedBox] = await Promise.all([saved.boundingBox(), unconfirmed.boundingBox()])
                expect(unconfirmedBox!.y).toBeGreaterThanOrEqual(savedBox!.y + savedBox!.height)
                await expect(status(productNewsId)).toHaveText('Not subscribed')
                await expect(productNews).not.toBeChecked()

                // Stacked messages can cover a switch, so a click there must still reach it.
                // A shorter window lets the page scroll a switch under them.
                await recipientPage.setViewportSize({ width: 1280, height: 400 })
                await eventInvites.evaluate(
                    (toggle, top) => window.scrollBy(0, toggle.getBoundingClientRect().top - top),
                    unconfirmedBox!.y + 8
                )
                // A message slides in, so it covers the switch only once it settles
                const switchUnderMessages = (): Promise<{ x: number; y: number } | null> =>
                    eventInvites.evaluate((toggle) => {
                        const box = toggle.getBoundingClientRect()
                        const [x, y] = [box.x + box.width / 2, box.y + box.height / 2]
                        const covered = Array.from(document.querySelectorAll('#toasts > *')).some((toast) => {
                            const area = toast.getBoundingClientRect()
                            return x >= area.left && x <= area.right && y >= area.top && y <= area.bottom
                        })
                        return covered ? { x, y } : null
                    })
                await expect.poll(switchUnderMessages).not.toBeNull()
                // A mouse click lands where the recipient points; a locator click would scroll the switch clear
                const point = await switchUnderMessages()
                await recipientPage.mouse.click(point!.x, point!.y)
                await expect(status(eventInvitesId)).toHaveText('Subscribed')
                await expect(eventInvites).toBeChecked()
                expect(await storedPreferences('product_news')).toEqual({
                    $all: 'OPTED_IN',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_IN',
                })
            })

            await test.step('a failed save whose read-back stalls still turns the switch back', async () => {
                const read = responseGate()
                await recipientPage.route(
                    UPDATE_URL,
                    (route) => route.fulfill({ status: 500, json: { error: 'Something went wrong' } }),
                    { times: 1 }
                )
                await recipientPage.route(isPageRead, () => read.open(), { times: 1 })
                // Safari before 16 has no AbortSignal.timeout
                await recipientPage.evaluate(() => Reflect.deleteProperty(AbortSignal, 'timeout'))
                await allMarketing.click()
                await read.opened
                // The refused change turns back before the read-back ends, so topics unlock at once
                await expect(allMarketing).toBeChecked()
                await expect(eventInvites).toBeEnabled()
                await expect(status('$all')).toHaveText('Saving…')
                await recipientPage.clock.runFor(10_000)
                await expect(
                    recipientPage.getByText("Couldn't confirm your preferences.", { exact: false })
                ).toBeVisible()
                await expect(status('$all')).toHaveText('Subscribed')
                await expect(allMarketing).toBeChecked()
                await expect(eventInvites).toBeEnabled()
                await expect(eventInvites).toBeChecked()
            })

            await test.step('an edit made while a failed save reads back does not resend the refused choice', async () => {
                const read = responseGate()
                const answer = responseGate()
                await recipientPage.route(
                    UPDATE_URL,
                    (route) => route.fulfill({ status: 500, json: { error: 'Something went wrong' } }),
                    { times: 1 }
                )
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
                await productNews.click()
                await read.opened
                await eventInvites.click()
                await expect(status(eventInvitesId)).toHaveText('Not subscribed')
                await expect(status(productNewsId)).toHaveText('Not subscribed')
                expect(await storedPreferences('product_news')).toEqual({
                    $all: 'OPTED_IN',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_OUT',
                })
                answer.open()
            })

            await test.step('a failed read-back after out-of-order answers keeps the last choice for the next save', async () => {
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
                await recipientPage.route(
                    isPageRead,
                    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<p>Another page</p>' }),
                    { times: 1 }
                )
                const unconfirmed = recipientPage.getByText("Couldn't confirm your preferences.", { exact: false })
                const warningsBefore = await unconfirmed.count()
                await allMarketing.click()
                await committed.opened
                const savedBefore = await successToast.count()
                await allMarketing.click()
                await expect(successToast).toHaveCount(savedBefore + 1)
                answer.open()
                await expect(unconfirmed).toHaveCount(warningsBefore + 1)
                await expect(status('$all')).toHaveText('Subscribed')
                await expect(allMarketing).toBeChecked()
                await eventInvites.click()
                await expect(status(eventInvitesId)).toHaveText('Subscribed')
                expect(await storedPreferences('product_news')).toEqual({
                    $all: 'OPTED_IN',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_IN',
                })
            })

            await test.step('a refusal that answers after a later save committed the same choice keeps it', async () => {
                const answer = responseGate()
                const read = responseGate()
                const readAnswer = responseGate()
                await recipientPage.route(
                    isPageRead,
                    async (route) => {
                        const response = await route.fetch()
                        read.open()
                        await readAnswer.opened
                        await route.fulfill({ response })
                    },
                    { times: 1 }
                )
                await recipientPage.route(
                    UPDATE_URL,
                    async (route) => {
                        await answer.opened
                        await route.fulfill({ status: 500, json: { error: 'Something went wrong' } })
                    },
                    { times: 1 }
                )
                const refusals = recipientPage.getByText('Something went wrong')
                const [savedBefore, refusedBefore] = [await successToast.count(), await refusals.count()]
                await eventInvites.click()
                await productNews.click()
                await expect(successToast).toHaveCount(savedBefore + 1)
                answer.open()
                await expect(refusals).toHaveCount(refusedBefore + 1)
                await read.opened
                await productNews.click()
                await expect(status(productNewsId)).toHaveText('Not subscribed')
                readAnswer.open()
                await expect(status(eventInvitesId)).toHaveText('Not subscribed')
                await expect(eventInvites).not.toBeChecked()
                expect(await storedPreferences('event_invites')).toEqual({
                    $all: 'OPTED_IN',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_OUT',
                })
            })

            await test.step('two refused saves both turn back before the next edit', async () => {
                const answer = responseGate()
                const read = responseGate()
                const readAnswer = responseGate()
                await recipientPage.route(
                    isPageRead,
                    async (route) => {
                        const response = await route.fetch()
                        read.open()
                        await readAnswer.opened
                        await route.fulfill({ response })
                    },
                    { times: 1 }
                )
                await recipientPage.route(
                    UPDATE_URL,
                    async (route) => {
                        await answer.opened
                        await route.fulfill({ status: 500, json: { error: 'Something went wrong' } })
                    },
                    { times: 2 }
                )
                const refusals = recipientPage.getByText('Something went wrong')
                const refusedBefore = await refusals.count()
                await eventInvites.click()
                await productNews.click()
                answer.open()
                await expect(refusals).toHaveCount(refusedBefore + 2)
                await read.opened
                await allMarketing.click()
                await expect(status('$all')).toHaveText('Not subscribed')
                readAnswer.open()
                expect(await storedPreferences()).toEqual({
                    $all: 'OPTED_OUT',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_OUT',
                })
            })

            await test.step('a refused tracking change turns back though a later save went through', async () => {
                const answer = responseGate()
                await recipientPage.route(
                    UPDATE_URL,
                    async (route) => {
                        await answer.opened
                        await route.fulfill({ status: 500, json: { error: 'Something went wrong' } })
                    },
                    { times: 1 }
                )
                await recipientPage.route(
                    isPageRead,
                    (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<p>Another page</p>' }),
                    { times: 1 }
                )
                const unconfirmed = recipientPage.getByText("Couldn't confirm your preferences.", { exact: false })
                const [savedBefore, warningsBefore] = [await successToast.count(), await unconfirmed.count()]
                await expect(tracking).toBeChecked()
                await tracking.click()
                await allMarketing.click()
                await expect(successToast).toHaveCount(savedBefore + 1)
                answer.open()
                await expect(unconfirmed).toHaveCount(warningsBefore + 1)
                await expect(status('$email_tracking')).toHaveText('Tracking allowed')
                await expect(tracking).toBeChecked()
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

    test('a refused change turns back unless the recipient clicked that switch again', async ({
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
        const tracking = recipientPage.getByRole('checkbox', { name: 'Open and click tracking' })
        const successToast = recipientPage.getByText('Preferences updated successfully')
        const refusals = recipientPage.getByText('Something went wrong')
        const isPageRead = (url: URL): boolean => url.pathname === path
        const status = (id: string): ReturnType<Page['getByTestId']> => recipientPage.getByTestId(`status-${id}`)
        const refuse = (route: Route): Promise<void> =>
            route.fulfill({ status: 500, json: { error: 'Something went wrong' } })
        // One handler takes every save in a step: a single-use route that ends lets a held save through
        let handleSave = async (route: Route): Promise<void> => route.continue()
        await recipientPage.route(UPDATE_URL, (route) => handleSave(route))

        try {
            // Messages leave on a timer, so a paused clock lets the steps count them
            await recipientPage.clock.install()
            await recipientPage.goto(path)
            await recipientPage.clock.pauseAt(Date.now() + 1000)
            await productNews.click()
            await expect(status(productNewsId)).toHaveText('Not subscribed')
            await expect(eventInvites).toBeChecked()
            await expect(tracking).toBeChecked()

            await test.step('a refused topic change turns back though a pending tracking save sent it', async () => {
                const topicRefusal = responseGate()
                const trackingRefusal = responseGate()
                let saves = 0
                handleSave = async (route) => {
                    saves++
                    if (saves === 1) {
                        await topicRefusal.opened
                        await refuse(route)
                    } else if (saves === 2) {
                        await trackingRefusal.opened
                        await refuse(route)
                    } else {
                        await route.continue()
                    }
                }
                await productNews.click()
                await tracking.click()
                topicRefusal.open()
                await expect(refusals).toHaveCount(1)
                await expect(productNews).not.toBeChecked()
                await eventInvites.click()
                await expect(successToast).toHaveCount(2)
                trackingRefusal.open()
                await expect(refusals).toHaveCount(2)
                await expect(status(eventInvitesId)).toHaveText('Not subscribed')
                await expect(status(productNewsId)).toHaveText('Not subscribed')
                await expect(status('$email_tracking')).toHaveText('Tracking allowed')
                expect(await storedPreferences('product_news')).toEqual({
                    $all: 'OPTED_IN',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_OUT',
                })
            })

            await test.step('a refused topic follows a later save that went through', async () => {
                await eventInvites.click()
                await expect(status(eventInvitesId)).toHaveText('Subscribed')
                const [refusal, committed, answer] = [responseGate(), responseGate(), responseGate()]
                const [read, readAnswer] = [responseGate(), responseGate()]
                const [savedBefore, refusedBefore] = [await successToast.count(), await refusals.count()]
                let saves = 0
                handleSave = async (route) => {
                    saves++
                    if (saves === 1) {
                        await refusal.opened
                        await refuse(route)
                    } else if (saves === 2) {
                        const response = await route.fetch()
                        committed.open()
                        await answer.opened
                        await route.fulfill({ response })
                    } else {
                        await route.continue()
                    }
                }
                await recipientPage.route(
                    isPageRead,
                    async (route) => {
                        const response = await route.fetch()
                        read.open()
                        await readAnswer.opened
                        await route.fulfill({ response })
                    },
                    { times: 1 }
                )
                await eventInvites.click()
                await tracking.click()
                await committed.opened
                refusal.open()
                await expect(refusals).toHaveCount(refusedBefore + 1)
                await expect(eventInvites).toBeChecked()
                answer.open()
                await read.opened
                await expect(eventInvites).not.toBeChecked()
                await tracking.click()
                await expect(successToast).toHaveCount(savedBefore + 2)
                readAnswer.open()
                await expect(status(eventInvitesId)).toHaveText('Not subscribed')
                await expect(status('$email_tracking')).toHaveText('Tracking allowed')
                expect(await storedPreferences('event_invites')).toEqual({
                    $all: 'OPTED_IN',
                    $email_tracking: 'OPTED_IN',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_OUT',
                })
            })

            await test.step('a late answer from an older save does not undo a newer one', async () => {
                const [refusal, trackingCommitted, trackingAnswer] = [responseGate(), responseGate(), responseGate()]
                const [topicCommitted, topicAnswer] = [responseGate(), responseGate()]
                const [savedBefore, refusedBefore] = [await successToast.count(), await refusals.count()]
                let saves = 0
                handleSave = async (route) => {
                    saves++
                    if (saves === 1) {
                        await refusal.opened
                        await refuse(route)
                    } else if (saves === 2 || saves === 3) {
                        const [committed, answer] =
                            saves === 2 ? [trackingCommitted, trackingAnswer] : [topicCommitted, topicAnswer]
                        const response = await route.fetch()
                        committed.open()
                        await answer.opened
                        await route.fulfill({ response })
                    } else {
                        await route.continue()
                    }
                }
                await productNews.click()
                await tracking.click()
                await trackingCommitted.opened
                refusal.open()
                await expect(refusals).toHaveCount(refusedBefore + 1)
                await expect(productNews).not.toBeChecked()
                await eventInvites.click()
                await topicCommitted.opened
                trackingAnswer.open()
                await expect(successToast).toHaveCount(savedBefore + 1)
                await expect(productNews).not.toBeChecked()
                await tracking.click()
                await expect(successToast).toHaveCount(savedBefore + 2)
                topicAnswer.open()
                await expect(status(eventInvitesId)).toHaveText('Subscribed')
                await expect(status(productNewsId)).toHaveText('Not subscribed')
                expect(await storedPreferences('product_news')).toEqual({
                    $all: 'OPTED_IN',
                    $email_tracking: 'OPTED_IN',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_IN',
                })
            })

            await test.step('a late answer from an older save applies once a newer save is refused', async () => {
                const [refusal, trackingCommitted, trackingAnswer, topicRefusal] = [
                    responseGate(),
                    responseGate(),
                    responseGate(),
                    responseGate(),
                ]
                const [read, readAnswer] = [responseGate(), responseGate()]
                const [savedBefore, refusedBefore] = [await successToast.count(), await refusals.count()]
                let saves = 0
                handleSave = async (route) => {
                    saves++
                    if (saves === 1 || saves === 3) {
                        await (saves === 1 ? refusal : topicRefusal).opened
                        await refuse(route)
                    } else if (saves === 2) {
                        const response = await route.fetch()
                        trackingCommitted.open()
                        await trackingAnswer.opened
                        await route.fulfill({ response })
                    } else {
                        await route.continue()
                    }
                }
                await recipientPage.route(
                    isPageRead,
                    async (route) => {
                        const response = await route.fetch()
                        read.open()
                        await readAnswer.opened
                        await route.fulfill({ response })
                    },
                    { times: 1 }
                )
                await eventInvites.click()
                await tracking.click()
                await trackingCommitted.opened
                refusal.open()
                await expect(refusals).toHaveCount(refusedBefore + 1)
                await expect(eventInvites).toBeChecked()
                await productNews.click()
                topicRefusal.open()
                await expect(refusals).toHaveCount(refusedBefore + 2)
                trackingAnswer.open()
                await read.opened
                await expect(eventInvites).not.toBeChecked()
                await tracking.click()
                await expect(successToast).toHaveCount(savedBefore + 2)
                readAnswer.open()
                await expect(status(eventInvitesId)).toHaveText('Not subscribed')
                await expect(status(productNewsId)).toHaveText('Not subscribed')
                expect(await storedPreferences('product_news')).toEqual({
                    $all: 'OPTED_IN',
                    $email_tracking: 'OPTED_IN',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_OUT',
                })
            })

            await test.step('an older refusal does not undo a newer click on the same switch', async () => {
                // A subscribed topic shows whether a save while all marketing is off keeps it
                await eventInvites.click()
                await expect(status(eventInvitesId)).toHaveText('Subscribed')
                const refusal = responseGate()
                const committed = responseGate()
                const answer = responseGate()
                let saves = 0
                handleSave = async (route) => {
                    saves++
                    if (saves === 1) {
                        await refusal.opened
                        await refuse(route)
                    } else if (saves === 3) {
                        const response = await route.fetch()
                        committed.open()
                        await answer.opened
                        await route.fulfill({ response })
                    } else {
                        await route.continue()
                    }
                }
                const [savedBefore, refusedBefore] = [await successToast.count(), await refusals.count()]
                await allMarketing.click()
                await allMarketing.click()
                await expect(successToast).toHaveCount(savedBefore + 1)
                await allMarketing.click()
                await committed.opened
                refusal.open()
                await expect(refusals).toHaveCount(refusedBefore + 1)
                await expect(allMarketing).not.toBeChecked()
                await tracking.click()
                answer.open()
                await expect(status('$email_tracking')).toHaveText('Tracking off')
                await expect(status('$all')).toHaveText('Not subscribed')
                expect(await storedPreferences()).toEqual({
                    $all: 'OPTED_OUT',
                    $email_tracking: 'OPTED_OUT',
                    [productNewsId]: 'OPTED_OUT',
                    [eventInvitesId]: 'OPTED_IN',
                })
            })
        } finally {
            await recipientContext.close()
        }
    })
})
