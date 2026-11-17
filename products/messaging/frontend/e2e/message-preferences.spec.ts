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
                let answerHeldSave = (): void => {}
                const heldSaveAnswered = new Promise<void>((resolve) => {
                    answerHeldSave = resolve
                })
                let heldSaveStored = (): void => {}
                const heldSaveCommitted = new Promise<void>((resolve) => {
                    heldSaveStored = resolve
                })
                await recipientPage.route(
                    UPDATE_URL,
                    async (route) => {
                        const response = await route.fetch()
                        heldSaveStored()
                        await heldSaveAnswered
                        await route.fulfill({ response })
                    },
                    { times: 1 }
                )
                await allMarketing.click()
                await heldSaveCommitted
                const laterSave = recipientPage.waitForResponse((response) =>
                    response.url().includes('/messaging-preferences/update')
                )
                await allMarketing.click()
                await laterSave
                answerHeldSave()

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
        } finally {
            await recipientContext.close()
        }
    })
})
