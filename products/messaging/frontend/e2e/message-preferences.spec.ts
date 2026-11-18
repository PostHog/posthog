import { PlaywrightSetup } from '@playwright-utils/playwright-setup'
import { expect, test } from '@playwright-utils/workspace-test-base'
import { Page } from '@playwright/test'

const RECIPIENT = 'reader@example.com'

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
        const offNote = recipientPage.getByText('These topics are off because all marketing communications are off.')
        const status = (id: string): ReturnType<Page['getByTestId']> => recipientPage.getByTestId(`${id}-status`)

        try {
            await recipientPage.goto(path)
            await eventInvites.click()
            await expect(status(eventInvitesId)).toHaveText('Not subscribed')
            await expect
                .poll(() => storedPreferences('event_invites'))
                .toEqual({ $all: 'OPTED_IN', [productNewsId]: 'OPTED_IN', [eventInvitesId]: 'OPTED_OUT' })

            await test.step('all marketing off greys out every topic and keeps the topic choices', async () => {
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
                await expect(productNews).not.toBeChecked()
                await expect(productNews).toBeDisabled()
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
                    .poll(() => storedPreferences('event_invites'))
                    .toEqual({ $all: 'OPTED_IN', [productNewsId]: 'OPTED_IN', [eventInvitesId]: 'OPTED_OUT' })
            })

            await test.step('a failed save turns the clicked switch back', async () => {
                await recipientPage.route(
                    '**/messaging-preferences/update*',
                    (route) => route.fulfill({ status: 500, json: { error: 'Something went wrong' } }),
                    { times: 1 }
                )
                await allMarketing.click()
                await expect(recipientPage.getByText('Something went wrong')).toBeVisible()
                await expect(allMarketing).toBeChecked()
                await expect(offNote).toBeHidden()
                await expect(productNews).toBeChecked()
                await expect(productNews).toBeEnabled()
            })

            await test.step('all marketing off during a pending topic save posts the new topic choice', async () => {
                let releaseTopicSave = (): void => {}
                let markTopicSaveHeld = (): void => {}
                const topicSaveHeld = new Promise<void>((held) => {
                    markTopicSaveHeld = held
                })
                await recipientPage.route(
                    '**/messaging-preferences/update*',
                    async (route) => {
                        await new Promise<void>((release) => {
                            releaseTopicSave = release
                            markTopicSaveHeld()
                        })
                        await route.continue()
                    },
                    { times: 1 }
                )
                await productNews.click()
                await topicSaveHeld
                await expect(status(productNewsId)).toHaveText('Saving…')

                const allOffSave = recipientPage.waitForRequest('**/messaging-preferences/update*')
                await allMarketing.click()
                const allOffBody = (await allOffSave).postData()
                expect(allOffBody).toContain(`${productNewsId}:false`)
                expect(allOffBody).not.toContain(`${productNewsId}:true`)

                releaseTopicSave()
                await expect(status(productNewsId)).toHaveText('Not subscribed')
            })
        } finally {
            await recipientContext.close()
        }
    })
})
