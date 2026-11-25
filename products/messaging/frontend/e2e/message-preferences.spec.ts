import { PlaywrightSetup } from '@playwright-utils/playwright-setup'
import { expect, test } from '@playwright-utils/workspace-test-base'
import { Browser, BrowserContext, Page, Route } from '@playwright/test'

const RECIPIENT = 'reader@example.com'
const UPDATE_URL = '**/messaging-preferences/update*'

interface PreferencesPage {
    path: string
    productNewsId: string
    eventInvitesId: string
    storedPreferences: () => Promise<Record<string, string> | undefined>
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
        // Not `toBeOK()`: its failure message prints the request headers, which hold the API key here
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

    // The opt-out list only returns recipients who opted out of the given topic. The test turns
    // Event invites off first and keeps it off, so this list returns the recipient's full row.
    const storedPreferences = async (): Promise<Record<string, string> | undefined> => {
        const response = await page.request.get(`${api}/messaging_preferences/opt_outs/`, {
            headers,
            params: { search: RECIPIENT, category_key: 'event_invites' },
        })
        expect(response.ok()).toBe(true)
        return (await response.json()).results[0]?.preferences
    }

    return { path, productNewsId: categoryIds[0], eventInvitesId: categoryIds[1], storedPreferences }
}

interface RecipientView {
    context: BrowserContext
    recipientPage: Page
    productNews: ReturnType<Page['getByRole']>
    eventInvites: ReturnType<Page['getByRole']>
    allMarketing: ReturnType<Page['getByRole']>
    offNote: ReturnType<Page['getByText']>
    status: (id: string) => ReturnType<Page['getByTestId']>
}

// The next save reaches the endpoint without its form fields, so the endpoint refuses it with its own error
async function refuseNextSave(recipientPage: Page, save: () => Promise<void>): Promise<void> {
    await recipientPage.route(
        UPDATE_URL,
        (route) => {
            const { 'content-length': _length, 'content-type': _type, ...headers } = route.request().headers()
            return route.continue({
                headers: { ...headers, 'content-type': 'application/x-www-form-urlencoded' },
                postData: 'refused=true',
            })
        },
        { times: 1 }
    )
    await save()
    await expect(recipientPage.getByText('Missing token')).toBeVisible()
}

async function openAsRecipient(browser: Browser, path: string): Promise<RecipientView> {
    const context = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const recipientPage = await context.newPage()
    await recipientPage.goto(path)
    return {
        context,
        recipientPage,
        productNews: recipientPage.getByRole('checkbox', { name: 'Product news' }),
        eventInvites: recipientPage.getByRole('checkbox', { name: 'Event invites' }),
        allMarketing: recipientPage.getByRole('checkbox', { name: 'All marketing communications' }),
        offNote: recipientPage.getByText('These topics are off because all marketing communications are off.'),
        status: (id) => recipientPage.getByTestId(`${id}-status`),
    }
}

// Each case is its own test declaration, because the flake check counts declarations to budget its repeat runs
async function checkRefusedTopicSave(
    browser: Browser,
    page: Page,
    playwrightSetup: PlaywrightSetup,
    startsChecked: boolean
): Promise<void> {
    const { path, productNewsId, eventInvitesId, storedPreferences } = await createPreferencesPage(
        page,
        playwrightSetup
    )
    const { context, recipientPage, productNews, eventInvites, allMarketing, status } = await openAsRecipient(
        browser,
        path
    )
    const savedText = startsChecked ? 'Subscribed' : 'Not subscribed'
    const storedProductNews = startsChecked ? 'OPTED_IN' : 'OPTED_OUT'

    try {
        await eventInvites.click()
        await expect(status(eventInvitesId)).toHaveText('Not subscribed')
        await productNews.setChecked(startsChecked)
        await expect(status(productNewsId)).toHaveText(savedText)
        await expect
            .poll(() => storedPreferences())
            .toEqual({ $all: 'OPTED_IN', [productNewsId]: storedProductNews, [eventInvitesId]: 'OPTED_OUT' })

        await refuseNextSave(recipientPage, () => productNews.click())
        await expect(productNews).toBeChecked({ checked: startsChecked })
        await expect(productNews).toBeEnabled()
        await expect(status(productNewsId)).toHaveText(savedText)

        // An all marketing save resubmits every topic's saved choice, so a refused choice
        // the page kept would reach storage here
        await allMarketing.click()
        await expect(status('$all')).toHaveText('Not subscribed')
        await expect
            .poll(() => storedPreferences())
            .toEqual({ $all: 'OPTED_OUT', [productNewsId]: storedProductNews, [eventInvitesId]: 'OPTED_OUT' })
    } finally {
        await context.close()
    }
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
        const { context, recipientPage, productNews, eventInvites, allMarketing, offNote, status } =
            await openAsRecipient(browser, path)

        try {
            await eventInvites.click()
            await expect(status(eventInvitesId)).toHaveText('Not subscribed')
            await expect
                .poll(() => storedPreferences())
                .toEqual({ $all: 'OPTED_IN', [productNewsId]: 'OPTED_IN', [eventInvitesId]: 'OPTED_OUT' })

            await test.step('all marketing off disables every topic and keeps the topic choices', async () => {
                await allMarketing.click()
                await expect(status('$all')).toHaveText('Not subscribed')
                await expect(offNote).toBeVisible()
                for (const [topic, id] of [
                    [productNews, productNewsId],
                    [eventInvites, eventInvitesId],
                ] as const) {
                    await expect(topic).not.toBeChecked()
                    await expect(topic).toBeDisabled()
                    await expect(status(id)).toHaveText('Not subscribed')
                }
                await expect
                    .poll(() => storedPreferences())
                    .toEqual({ $all: 'OPTED_OUT', [productNewsId]: 'OPTED_IN', [eventInvitesId]: 'OPTED_OUT' })
            })

            await test.step('a reload keeps all marketing off', async () => {
                await recipientPage.reload()
                await expect(allMarketing).not.toBeChecked()
                await expect(offNote).toBeVisible()
                for (const topic of [productNews, eventInvites]) {
                    await expect(topic).not.toBeChecked()
                    await expect(topic).toBeDisabled()
                }
            })

            await test.step('all marketing on restores each topic to its saved choice', async () => {
                await allMarketing.click()
                await expect(status('$all')).toHaveText('Subscribed')
                await expect(offNote).toBeHidden()
                await expect(status(productNewsId)).toHaveText('Subscribed')
                await expect(productNews).toBeChecked()
                await expect(productNews).toBeEnabled()
                await expect(eventInvites).not.toBeChecked()
                await expect(eventInvites).toBeEnabled()
                await expect(status(eventInvitesId)).toHaveText('Not subscribed')
                await expect
                    .poll(() => storedPreferences())
                    .toEqual({ $all: 'OPTED_IN', [productNewsId]: 'OPTED_IN', [eventInvitesId]: 'OPTED_OUT' })
            })
        } finally {
            await context.close()
        }
    })

    test('a refused all marketing save turns all marketing back on and keeps the topic choices', async ({
        browser,
        page,
        playwrightSetup,
    }) => {
        const { path, productNewsId, eventInvitesId, storedPreferences } = await createPreferencesPage(
            page,
            playwrightSetup
        )
        const { context, recipientPage, productNews, eventInvites, allMarketing, offNote, status } =
            await openAsRecipient(browser, path)

        try {
            await eventInvites.click()
            await expect(status(eventInvitesId)).toHaveText('Not subscribed')

            await refuseNextSave(recipientPage, () => allMarketing.click())
            await expect(allMarketing).toBeChecked()
            await expect(status('$all')).toHaveText('Subscribed')
            await expect(offNote).toBeHidden()
            await expect(productNews).toBeChecked()
            await expect(productNews).toBeEnabled()
            await expect(status(productNewsId)).toHaveText('Subscribed')
            await expect(eventInvites).not.toBeChecked()
            await expect(eventInvites).toBeEnabled()
            await expect(status(eventInvitesId)).toHaveText('Not subscribed')

            await allMarketing.click()
            await expect(status('$all')).toHaveText('Not subscribed')
            await expect
                .poll(() => storedPreferences())
                .toEqual({ $all: 'OPTED_OUT', [productNewsId]: 'OPTED_IN', [eventInvitesId]: 'OPTED_OUT' })
        } finally {
            await context.close()
        }
    })

    test('all marketing off during a pending topic save keeps the new topic choice', async ({
        browser,
        page,
        playwrightSetup,
    }) => {
        const { path, productNewsId, eventInvitesId, storedPreferences } = await createPreferencesPage(
            page,
            playwrightSetup
        )
        const { context, recipientPage, productNews, eventInvites, allMarketing, status } = await openAsRecipient(
            browser,
            path
        )

        try {
            await eventInvites.click()
            await expect(status(eventInvitesId)).toHaveText('Not subscribed')

            let holding = true
            const heldSaves: (() => void)[] = []
            const holdSave = async (route: Route): Promise<void> => {
                if (holding) {
                    await new Promise<void>((release) => heldSaves.push(release))
                }
                await route.continue()
            }
            // No `times` limit: once a limited handler runs out, Playwright turns interception off,
            // which lets a held save through before the test releases it
            await recipientPage.route(UPDATE_URL, holdSave)
            await productNews.click()
            await expect.poll(() => heldSaves.length).toBe(1)
            await expect(status(productNewsId)).toHaveText('Saving…')
            await allMarketing.click()

            // The topic save commits first. Any later save the page sends, at once or after the
            // topic save returns, goes through only after that
            const topicSaved = recipientPage.waitForResponse(UPDATE_URL)
            heldSaves[0]()
            // A failed topic save would leave a later save to store the new topic choice on its own
            expect((await topicSaved).ok()).toBe(true)
            holding = false
            heldSaves.splice(1).forEach((release) => release())

            await expect(status('$all')).toHaveText('Not subscribed')
            await expect(status(productNewsId)).toHaveText('Not subscribed')
            await expect
                .poll(() => storedPreferences())
                .toEqual({ $all: 'OPTED_OUT', [productNewsId]: 'OPTED_OUT', [eventInvitesId]: 'OPTED_OUT' })
            await recipientPage.unroute(UPDATE_URL, holdSave)

            await recipientPage.reload()
            await allMarketing.click()
            await expect(status('$all')).toHaveText('Subscribed')
            await expect(productNews).not.toBeChecked()
            await expect(productNews).toBeEnabled()
            await expect(status(productNewsId)).toHaveText('Not subscribed')
            await expect
                .poll(() => storedPreferences())
                .toEqual({ $all: 'OPTED_IN', [productNewsId]: 'OPTED_OUT', [eventInvitesId]: 'OPTED_OUT' })
        } finally {
            await context.close()
        }
    })

    test('a refused topic save keeps the saved choice when the topic starts on', async ({
        browser,
        page,
        playwrightSetup,
    }) => {
        await checkRefusedTopicSave(browser, page, playwrightSetup, true)
    })

    test('a refused topic save keeps the saved choice when the topic starts off', async ({
        browser,
        page,
        playwrightSetup,
    }) => {
        await checkRefusedTopicSave(browser, page, playwrightSetup, false)
    })
})
