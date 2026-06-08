import { randomString } from '@playwright-utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '@playwright-utils/workspace-test-base'
import { Page } from '@playwright/test'

async function deleteSurvey(page: Page, name: string): Promise<void> {
    // Only archived surveys (or drafts) expose the "Delete permanently" action.
    await page.locator('[data-attr=open-context-panel-button]').first().click()
    await page.locator('[data-attr=survey-archive]').click()

    const archiveDialog = page.locator('.LemonModal__layout').filter({ hasText: 'Archive this survey?' })
    await expect(archiveDialog).toBeVisible()
    // The confirm button reads "Archive" when stopped but "Stop and archive" if the
    // dialog still sees the survey as running (end_date not yet propagated), so match both.
    await archiveDialog.getByRole('button', { name: /^(Archive|Stop and archive)$/ }).click()
    await expect(archiveDialog).not.toBeVisible()

    // Context menu is open again after archiving, so we can click "Delete permanently" right away
    await page.locator('[data-attr=survey-delete]').click()

    const deleteDialog = page.locator('.LemonModal__layout').filter({ hasText: 'Permanently delete this survey?' })
    await expect(deleteDialog).toBeVisible()
    await deleteDialog.getByRole('button', { name: 'Delete permanently' }).click()

    await expect(page.locator(`[data-row-key="${name}"]`)).not.toBeVisible()
}

async function expectNoToastErrors(page: Page): Promise<void> {
    const toastErrors = await page.locator('[data-attr="toast-error"]').all()
    if (toastErrors.length > 0) {
        throw new Error(`Found ${toastErrors.length} toast errors`)
    }
}

async function launchSurveyEvenIfDisabled(page: Page): Promise<void> {
    // check if page.getByText('Surveys are currently disabled') is visible
    if (await page.getByText('Surveys are currently disabled').isVisible()) {
        await page.getByRole('button', { name: 'Configure' }).click()
        await page.getByTestId('opt-in-surveys-switch').click()
        await page.getByRole('button', { name: 'Done' }).click()
    }

    // The launch control is now a split button, so two elements carry data-attr="launch-survey"
    // ("Launch" and "Launch survey"). Target the primary "Launch" button explicitly.
    await page.getByRole('button', { name: 'Launch', exact: true }).click()
    await expect(page.locator('.LemonModal__layout')).toBeVisible()
    await expect(page.getByText('Launch this survey?')).toBeVisible()
    const launchResponsePromise = page.waitForResponse(
        (resp) => resp.url().includes('/surveys') && resp.request().method() === 'PATCH'
    )
    await page.locator('.LemonModal__footer').getByRole('button', { name: 'Launch' }).click()
    await launchResponsePromise
}

// CI is too slow, these all fail when run in parallel, will try to find a better solution soon
test.describe.configure({ mode: 'serial' })

test.describe('CRUD Survey', () => {
    let name: string
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    // Keep demo data: one test targets the `email` person property in the taxonomic filter.
    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        name = randomString('survey-')
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
        await page.goToMenuItem('surveys')
    })

    test('creates, launches, edits and deletes new survey', async ({ page }) => {
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

        await launchSurveyEvenIfDisabled(page)

        await page.getByText('Stop').click()
        await expect(page.locator('.LemonModal__layout')).toBeVisible()
        await expect(page.getByText('Stop this survey?')).toBeVisible()
        await page.locator('.LemonModal__footer').getByRole('button', { name: 'Stop' }).click()

        await page.goToMenuItem('surveys')
        await expect(page.locator('[data-attr=surveys-table]')).toContainText(name)

        await page.locator(`[data-row-key="${name}"]`).getByText(name).click()

        await page.locator('.LemonTabs').getByText('Overview').click()
        await expect(page.getByText('Display conditions summary')).toBeVisible()
        await expect(
            page.getByText('Surveys will be displayed to users that match the following conditions')
        ).toBeVisible()

        await deleteSurvey(page, name)
    })

    test('can set responses limit', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        // This test exercises the full editor's adaptive sampling UI. The
        // "new survey" URL auto-redirects to whichever editor the user
        // previously preferred (default: guided wizard), so force the
        // preference to 'full' before navigating.
        await page.addInitScript(() => {
            localStorage.setItem('scenes.surveys.surveysLogic.preferredEditor', JSON.stringify('full'))
        })
        await page.goto('/surveys/new')

        await page.locator('[data-attr="scene-title-textarea"]').fill(name)

        await page.locator('.LemonCollapsePanel', { hasText: 'Completion conditions' }).click()
        await page.locator('[data-attr=survey-collection-until-limit]').first().click()
        await page.locator('[data-attr=survey-responses-limit-input]').fill('228')
        await page.locator('[data-attr="scene-title-textarea"]').click()

        const saveButton = page.locator('[data-attr=save-survey]').first()
        await expect(saveButton).toBeEnabled()
        const saveResponsePromise = page.waitForResponse(
            (resp) => resp.url().includes('/surveys') && resp.request().method() === 'POST'
        )
        await saveButton.click()
        await saveResponsePromise

        await expect(page.locator('button[data-attr="launch-survey"]').first()).toContainText('Launch')

        await page.reload()
        await expect(page.getByText('The survey will be stopped once 228 responses are received.')).toBeVisible()

        await deleteSurvey(page, name)
    })

    test('can set cancellation events', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        // Cancellation events aren't exposed in the guided wizard. Force the
        // editor preference to 'full' so the /surveys/new redirect doesn't
        // send us into the wizard.
        await page.addInitScript(() => {
            localStorage.setItem('scenes.surveys.surveysLogic.preferredEditor', JSON.stringify('full'))
        })
        await page.goto('/surveys/new')

        await page.locator('[data-attr="scene-title-textarea"]').fill(name)

        await page.getByText('Customization').click()
        await page.locator('[data-attr="survey-popup-delay-input"]').fill('5')

        await page.locator('.LemonButton').getByText('Display conditions').click()
        // Display conditions is now a LemonRadio whose outer data-attr is not
        // forwarded to the DOM (only inner option `data-attr`s are). Click the
        // "match conditions" radio option directly.
        await page.locator('[data-attr="survey-display-conditions-select-users"]').click()

        await expect(page.getByText('Cancel survey on events')).toBeVisible()

        await page.locator('.LemonButton').getByText('Add cancel event').click()
        await page.locator('span[aria-label="Autocapture"]').getByText('Autocapture').click()

        await page.locator('[data-attr=save-survey]').first().click()
        await expect(page.locator('button[data-attr="launch-survey"]').first()).toContainText('Launch')

        await page.locator('.LemonTabs__tab').getByText('Overview').click()
        await expect(page.getByText('Delay before showing: 5 seconds')).toBeVisible()
        await expect(page.getByText('Cancel survey if user sends:$autocapture')).toBeVisible()
    })
})
