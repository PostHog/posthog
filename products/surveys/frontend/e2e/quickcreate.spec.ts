import { randomString } from '@playwright-utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '@playwright-utils/workspace-test-base'
import { Page } from '@playwright/test'

import { urls } from 'scenes/urls'

const saveFeatureFlag = async (page: Page): Promise<void> => {
    const saveButton = page.locator('[data-attr="save-feature-flag"]').first()
    await expect(saveButton).toBeEnabled()
    const responsePromise = page.waitForResponse(
        (resp) => resp.url().includes('/feature_flags') && resp.request().method() === 'POST'
    )
    await saveButton.click()
    await responsePromise
    // Saving redirects to the flag's own detail page (featureFlagLogic.saveFeatureFlagSuccess).
    // Waiting for that confirms the flag was created and committed before clickCreateSurvey
    // navigates to the list to find it.
    await page.waitForURL(/\/feature_flags\/\d+/)
}

const expectFlagEnabled = async (page: Page, name: string): Promise<void> => {
    await expect(page.getByText(`Feature flag enabled for: ${name}`)).toBeVisible()
}

const expectVariant = async (page: Page, variant?: string): Promise<void> => {
    if (!variant) {
        return await expect(page.locator('.LemonTag').getByText('variant:')).not.toBeVisible()
    }

    await expect(page.locator('.LemonTag').getByText(`variant: ${variant}`)).toBeVisible()
}

const expectEvents = async (page: Page, events: string[]): Promise<void> => {
    if (events.length === 0) {
        return await expect(page.getByText('When the user sends the following events')).not.toBeVisible()
    }

    const eventsSpan = page.getByText('When the user sends the following events')
    const eventsSection = eventsSpan.locator('..')

    await expect(eventsSpan).toBeVisible()
    for (const event of events) {
        await expect(eventsSection.locator('.LemonTag').getByText(event)).toBeVisible()
    }
}

const addTwoVariants = async (page: Page): Promise<void> => {
    await page.getByText('Multiple variants with rollout percentages (A/B/n test)').click()
    // Default multivariate includes control/test at 50/50, each in a collapsed row, so expand then rename them
    await page.getByRole('button', { name: 'Expand all' }).click()
    await page.locator('[data-attr="feature-flag-variant-key-0"]').fill('test-1')
    await page.locator('[data-attr="feature-flag-variant-key-1"]').fill('test-2')
}

const clickCreateSurvey = async (page: Page, name: string): Promise<void> => {
    // Create the survey from the feature-flag list row's "more" menu. The flag detail page's
    // create-survey action lives in the global scene side panel, whose open/closed state and
    // active tab persist across navigation and whose toggle button unmounts while it's open —
    // too stateful to drive reliably. The list menu opens the same QuickSurveyModal with no
    // side panel involved. The workspace is isolated (only this flag exists), so reload the
    // list until the row shows up, then act on it.
    const row = page.locator(`[data-row-key="${name}"]`)
    await expect(async () => {
        await page.goto(urls.featureFlags())
        await expect(row).toBeVisible({ timeout: 10_000 })
    }).toPass({ timeout: 40_000 })
    await row.locator('[data-attr="more-button"]').click()
    await page.locator('[data-attr="create-survey"]').click()
}

const goToSurveyOverview = async (page: Page): Promise<void> => {
    await page.locator('.LemonTabs__tab').getByText('Overview').click()
}

const launchSurvey = async (page: Page, name: string): Promise<void> => {
    const createButton = page.getByTestId('quick-survey-create')
    await expect(createButton).toBeEnabled()
    const responsePromise = page.waitForResponse(
        (resp) => resp.url().includes('/surveys') && resp.request().method() === 'POST'
    )
    await createButton.click()
    await responsePromise
    await page.waitForURL(/project\/(\d+)\/surveys\/([\w-]+)/)
    await expect(page.locator('[data-attr="scene-name"]').first()).toContainText(name)
    await expect(page.locator('[data-attr="stop-survey"]')).toBeVisible()
}

// Run serially to keep per-test workspace setup off the critical path and avoid hammering
// the setup endpoint with concurrent organization_with_team calls.
test.describe.configure({ mode: 'serial' })

test.describe('Quick create survey from feature flag', () => {
    let name: string
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeEach(async ({ page, playwrightSetup }) => {
        // Dedicated empty workspace per test — no shared demo team, so the feature-flag
        // list only contains the flag this test creates.
        // Seed a *recent* $autocapture event: the survey event picker (Events taxonomic list)
        // sends exclude_stale=true, which drops definitions whose last_seen_at is >30 days old —
        // so a fixed past timestamp never surfaced "Autocapture". `now` keeps it non-stale.
        workspace = await playwrightSetup.createWorkspace({
            skip_onboarding: true,
            no_demo_data: true,
            events: [{ event: '$autocapture', distinct_id: 'survey-seed-user', timestamp: new Date().toISOString() }],
        })
        await playwrightSetup.login(page, workspace)

        name = randomString('ff')
        await page.goto(urls.featureFlags())
        await expect(page.locator('h1')).toContainText('Feature flags')

        await page.evaluate(() => {
            window.posthog?.featureFlags?.override({})
        })

        // start ff creation
        await page.locator('[data-attr="new-feature-flag"]').click()
        await page.locator('[data-attr="blank-feature-flag-template"]').click()
        await page.locator('[data-attr="feature-flag-key"]').fill(name)
        await page.locator('[data-attr="rollout-percentage"]').fill('100')
    })

    test('launch basic survey from single variant feature flag', async ({ page }) => {
        // use defaults for basic ff
        await saveFeatureFlag(page)

        await clickCreateSurvey(page, name)

        await launchSurvey(page, name)

        await goToSurveyOverview(page)
        await expectFlagEnabled(page, name)
        await expectVariant(page, undefined)
        await expectEvents(page, [])
    })

    test('launch basic survey from multivariant feature flag', async ({ page }) => {
        await addTwoVariants(page)
        await saveFeatureFlag(page)

        await clickCreateSurvey(page, name)

        await launchSurvey(page, name)

        await goToSurveyOverview(page)
        await expectFlagEnabled(page, name)
        await expectVariant(page, undefined)
        await expectEvents(page, [])
    })

    test('launch variant-specific survey from multivariant feature flag', async ({ page }) => {
        // add variants
        await addTwoVariants(page)
        await saveFeatureFlag(page)

        await clickCreateSurvey(page, name)

        // select variant test-1
        await page.getByText(`Only users in the test-1 variant`).locator('..').locator('input').click()

        await launchSurvey(page, name)
        await goToSurveyOverview(page)
        await expectFlagEnabled(page, name)
        await expectVariant(page, 'test-1')
        await expectEvents(page, [])
    })

    test('launch survey with event', async ({ page }) => {
        await saveFeatureFlag(page)
        await clickCreateSurvey(page, name)

        // add event — the beforeEach seeds a recent $autocapture event, so its definition shows
        // as "Autocapture" in the picker's Events list (no search needed).
        await page.locator('.LemonButton').getByText('Add event').click()
        const autocaptureOption = page.locator('span[aria-label="Autocapture"]').getByText('Autocapture')
        await expect(autocaptureOption).toBeVisible()
        await autocaptureOption.click()

        await launchSurvey(page, name)
        await goToSurveyOverview(page)
        await expectFlagEnabled(page, name)
        await expectVariant(page, undefined)
        await expectEvents(page, ['$autocapture'])
    })

    test('survey responses visible in feature flag feedback tab', async ({ page }) => {
        await saveFeatureFlag(page)
        await clickCreateSurvey(page, name)
        await launchSurvey(page, name)
        await goToSurveyOverview(page)

        const ffLink = page.getByText(`Feature flag enabled for: ${name}`).locator('a[href]')
        await expect(ffLink).toBeVisible()
        const ffUrl = await ffLink.getAttribute('href')
        // Don't wait for networkidle — PostHog polls continuously, so it rarely settles. goto
        // already waits for the navigation to load.
        await page.goto(ffUrl!)

        await page.locator('.LemonTabs__tab').getByText('User feedback').click()
        await expect(page.getByText('Filter survey results')).toBeVisible()
    })

    test('list of surveys in ff feedback tab when multiple surveys exist', async ({ page }) => {
        await addTwoVariants(page)
        await saveFeatureFlag(page)

        await clickCreateSurvey(page, name)
        await page.getByText(`Only users in the test-1 variant`).locator('..').locator('input').click()
        await launchSurvey(page, name)

        // Second survey (test-2 variant) — clickCreateSurvey navigates back to the flag list itself.
        await clickCreateSurvey(page, name)
        await page.getByText(`Only users in the test-2 variant`).locator('..').locator('input').click()
        await launchSurvey(page, name)

        await goToSurveyOverview(page)

        const ffLink = page.getByText(`Feature flag enabled for: ${name}`).locator('a[href]')
        await expect(ffLink).toBeVisible()
        const ffUrl = await ffLink.getAttribute('href')
        // Don't wait for networkidle — PostHog polls continuously, so it rarely settles. goto
        // already waits for the navigation to load.
        await page.goto(ffUrl!)

        await page.locator('.LemonTabs__tab').getByText('User feedback').click()
        await expect(page.locator('[data-attr="surveys-table"]')).toBeVisible()
    })

    test('create draft survey', async ({ page }) => {
        await saveFeatureFlag(page)
        await clickCreateSurvey(page, name)

        await page
            .getByTestId('quick-survey-create')
            .locator('..')
            .locator('.LemonButtonWithSideAction__side-button button')
            .click()

        const saveAsDraftButton = page.getByText('Save as draft')
        await expect(saveAsDraftButton).toBeVisible()
        const responsePromise = page.waitForResponse(
            (resp) => resp.url().includes('/surveys') && resp.request().method() === 'POST'
        )
        await saveAsDraftButton.click()
        await responsePromise
        await page.waitForURL(/project\/(\d+)\/surveys\/([\w-]+)/)
        await expect(page.locator('[data-attr="scene-name"]').first()).toContainText(name)
        await expect(page.locator('[data-attr="launch-survey"]').getByText('Launch', { exact: true })).toBeVisible()
    })

    test('warning shown when surveys are disabled', async ({ page }) => {
        await saveFeatureFlag(page)

        // The team data comes from POSTHOG_APP_CONTEXT which is server-rendered into HTML.
        // API mocks don't work because teamLogic uses the preloaded context directly.
        // We need to intercept and modify the context before React hydrates.
        await page.addInitScript(() => {
            let _context: any = undefined
            Object.defineProperty(window, 'POSTHOG_APP_CONTEXT', {
                get() {
                    if (_context?.current_team) {
                        _context.current_team.surveys_opt_in = false
                    }
                    return _context
                },
                set(value) {
                    _context = value
                },
                configurable: true,
            })
        })

        await page.reload()
        await clickCreateSurvey(page, name)

        await expect(page.locator('label').getByText('Enable surveys')).toBeVisible()
    })
})
