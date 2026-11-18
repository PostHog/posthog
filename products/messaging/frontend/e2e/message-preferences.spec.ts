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

            await test.step('all marketing off during a pending topic save keeps the new topic choice', async () => {
                const heldSaves: (() => void)[] = []
                const holdSave = async (route: Route): Promise<void> => {
                    await new Promise<void>((release) => heldSaves.push(release))
                    await route.continue()
                }
                // No `times` limit: once a limited handler runs out, Playwright turns interception off,
                // which lets the other held save through before the test releases it
                await recipientPage.route(UPDATE_URL, holdSave)
                await productNews.click()
                await expect.poll(() => heldSaves.length).toBe(1)
                await expect(status(productNewsId)).toHaveText('Saving…')
                await allMarketing.click()
                await expect.poll(() => heldSaves.length).toBe(2)

                const topicSaved = recipientPage.waitForResponse(UPDATE_URL)
                heldSaves[0]()
                await topicSaved
                const allOffSaved = recipientPage.waitForResponse(UPDATE_URL)
                heldSaves[1]()
                await allOffSaved
                await recipientPage.unroute(UPDATE_URL, holdSave)

                await expect(status('$all')).toHaveText('Not subscribed')
                await expect(status(productNewsId)).toHaveText('Not subscribed')
                await expect
                    .poll(() => storedPreferences())
                    .toEqual({ $all: 'OPTED_OUT', [productNewsId]: 'OPTED_OUT', [eventInvitesId]: 'OPTED_OUT' })
            })

            await test.step('all marketing on afterwards keeps that topic off', async () => {
                await recipientPage.reload()
                await allMarketing.click()
                await expect(status('$all')).toHaveText('Subscribed')
                await expect(productNews).not.toBeChecked()
                await expect(productNews).toBeEnabled()
                await expect(status(productNewsId)).toHaveText('Not subscribed')
                await expect
                    .poll(() => storedPreferences())
                    .toEqual({ $all: 'OPTED_IN', [productNewsId]: 'OPTED_OUT', [eventInvitesId]: 'OPTED_OUT' })
            })
        } finally {
            await context.close()
        }
    })

    test('a refused save turns the switch back', async ({ browser, page, playwrightSetup }) => {
        const { path, productNewsId } = await createPreferencesPage(page, playwrightSetup)
        const { context, recipientPage, productNews, allMarketing, offNote, status } = await openAsRecipient(
            browser,
            path
        )

        try {
            await test.step('a refused all marketing save turns all marketing back on', async () => {
                await recipientPage.route(
                    UPDATE_URL,
                    (route) => route.fulfill({ status: 500, json: { error: 'All marketing save refused' } }),
                    { times: 1 }
                )
                await allMarketing.click()
                await expect(recipientPage.getByText('All marketing save refused')).toBeVisible()
                await expect(allMarketing).toBeChecked()
                await expect(status('$all')).toHaveText('Subscribed')
                await expect(offNote).toBeHidden()
                await expect(productNews).toBeChecked()
                await expect(productNews).toBeEnabled()
            })

            await test.step('a refused topic save turns the topic back on', async () => {
                await recipientPage.route(
                    UPDATE_URL,
                    (route) => route.fulfill({ status: 500, json: { error: 'Topic save refused' } }),
                    { times: 1 }
                )
                await productNews.click()
                await expect(recipientPage.getByText('Topic save refused')).toBeVisible()
                await expect(productNews).toBeChecked()
                await expect(productNews).toBeEnabled()
                await expect(status(productNewsId)).toHaveText('Subscribed')
            })
        } finally {
            await context.close()
        }
    })
})
