import { randomString } from '@playwright-utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '@playwright-utils/workspace-test-base'
import { Page } from '@playwright/test'

async function expectNoToastErrors(page: Page): Promise<void> {
    const toastErrors = await page.locator('[data-attr="toast-error"]').all()
    if (toastErrors.length > 0) {
        throw new Error(`Found ${toastErrors.length} toast errors`)
    }
}

test.describe('CRUD Survey', () => {
    let name: string
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    // Keep demo data: the test targets the `email` person property in the taxonomic filter.
    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        name = randomString('survey-')
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
        await page.goToMenuItem('surveys')
    })

    test('rating question type, scale, and display-condition targeting update the editor and preview', async ({
        page,
    }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await page.addInitScript(() => {
            localStorage.setItem('scenes.surveys.surveysLogic.preferredEditor', JSON.stringify('full'))
        })
        await page.goto('/surveys/new')

        await page.locator('[data-attr="scene-title-textarea"]').fill(name)
        await page.locator('[data-attr="survey-question-type-0"]').click()
        await page.locator('[data-attr="survey-question-type-0-rating"]').click()

        await expect(page.locator('[data-attr="survey-question-label-0"]')).toHaveValue(
            /How likely are you to recommend/
        )

        await expect(page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]')).toContainText(
            '0 - 10'
        )

        await expect(
            page
                .locator('.Field', { has: page.locator('.LemonLabel', { hasText: 'Upper bound label' }) })
                .locator('input')
        ).toHaveValue('Very likely')

        await page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]').click()
        await expect(page.locator('.Popover__content')).toBeVisible()
        await page.locator('.Popover__content').getByText('1 - 5').click()

        await expect(page.locator('[id="scenes.surveys.surveyLogic.new.survey.questions.0.scale"]')).toContainText(
            '1 - 5'
        )

        const surveyForm = page.locator('.survey-form')
        await expect(surveyForm).toContainText('How likely are you to recommend us to a friend?')
        await expect(surveyForm).toContainText('Unlikely')
        await expect(surveyForm).toContainText('Very likely')
        await expect(surveyForm.locator('.ratings-number')).toHaveCount(5)

        await page.locator('.LemonCollapsePanel', { hasText: 'Display conditions' }).click()
        await page.locator('[data-attr="survey-display-conditions-select-users"]').click()

        await page.locator('body').evaluate((el) => el.scrollTo(0, el.scrollHeight))

        await page.getByRole('button', { name: 'Add property targeting' }).click()
        await page.getByRole('button', { name: 'Add condition', exact: true }).click()
        await page.locator('[data-attr=taxonomic-filter-searchfield]').fill('email')
        await page.locator('.taxonomic-list-row').getByText('email').first().click()

        await page.locator('span').filter({ hasText: 'Enter value...' }).click()
        await page.getByPlaceholder('Enter value...').fill('t')
        await page.getByPlaceholder('Enter value...').press('Enter')

        const rolloutInput = page.locator('[data-attr="rollout-percentage"]')
        await rolloutInput.click()
        await rolloutInput.fill('50')

        const saveButton = page.locator('[data-attr="save-survey"]').nth(0)
        await expect(saveButton).toBeEnabled()
        const saveResponsePromise = page.waitForResponse(
            (resp) => resp.url().includes('/surveys') && resp.request().method() === 'POST'
        )
        await saveButton.click()
        await saveResponsePromise
        await expectNoToastErrors(page)

        await expect(page.locator('[data-attr=success-toast]')).toContainText('created')

        await expect(page.getByText('Display conditions summary')).toBeVisible()
        await expect(page.locator('.FeatureConditionCard')).toContainText('Rolled out to 50% of users in this set.')
    })
})
