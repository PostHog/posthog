import { PlaywrightWorkspaceSetupResult, expect, test } from '@playwright-utils/workspace-test-base'
import { Page } from '@playwright/test'

test.describe('Survey Settings', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
        // The scene shows its setup empty state, tab bar included, until the project
        // holds a survey. Seed one over the API so the Settings tab is reachable.
        await seedSurvey(page, workspace!)
        await page.goToMenuItem('surveys')
    })

    async function seedSurvey(page: Page, workspace: PlaywrightWorkspaceSetupResult): Promise<void> {
        const response = await page.request.post(`/api/projects/${workspace.team_id}/surveys/`, {
            headers: {
                Authorization: `Bearer ${workspace.personal_api_key}`,
                'Content-Type': 'application/json',
            },
            data: {
                name: 'Settings fixture survey',
                type: 'popover',
                questions: [{ type: 'open', question: 'How is it going?' }],
            },
        })
        expect(response.ok()).toBe(true)
    }

    async function toggleSurveysSettingsAndWaitResponse(page: Page): Promise<void> {
        const responsePromise = page.waitForResponse(
            (resp) => resp.url().includes('/api/environments/') && resp.request().method() === 'PATCH'
        )
        await page.locator('[data-attr="opt-in-surveys-switch"]').click()
        await responsePromise
        await expect(page.getByTestId('opt-in-surveys-switch')).not.toBeDisabled()
        await expect(page.getByText('Surveys opt in updated').first()).toBeVisible()
        await page.getByTestId('toast-close-button').first().click()
        await expect(page.getByText('Surveys opt in updated')).toHaveCount(0)
    }

    test('toggles survey opt in on the survey settings page', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')
        await page.getByRole('tab', { name: 'Settings' }).click()
        await expect(page.getByTestId('opt-in-surveys-switch')).not.toBeDisabled()
        await expect(page.getByText('Surveys opt in updated')).not.toBeVisible()
        await toggleSurveysSettingsAndWaitResponse(page)
        await toggleSurveysSettingsAndWaitResponse(page)
    })

    test('toggles survey opt in on the org settings page', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await page.goToMenuItem('settings')
        await page.locator('#main-content').getByRole('link', { name: 'Surveys', exact: true }).click()
        await expect(page.getByTestId('opt-in-surveys-switch')).not.toBeDisabled()
        await expect(page.getByText('Surveys opt in updated')).not.toBeVisible()
        await toggleSurveysSettingsAndWaitResponse(page)
        await toggleSurveysSettingsAndWaitResponse(page)
    })
})
