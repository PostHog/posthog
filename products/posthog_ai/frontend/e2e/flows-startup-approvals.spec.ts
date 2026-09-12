import { Locator, Page } from '@playwright/test'

import { NEXT_RUN_ID, approval, expect, message, notification, test } from './runSurfaceTest'

const feedback = (page: Page): Locator =>
    page.getByTestId('run-approval').getByPlaceholder(/tell the agent what to do differently/i)

async function submitFeedback(page: Page): Promise<void> {
    await feedback(page).fill('Use the synthetic preview environment.')
    await feedback(page).press('Enter')
}

async function retryFeedback(page: Page): Promise<void> {
    await expect(feedback(page)).toHaveValue('Use the synthetic preview environment.')
    await feedback(page).press('Enter')
}

const approvalCases = [
    {
        kind: 'permission' as const,
        submit: async (page: Page) => {
            await page.getByTestId('run-approval').getByText('Do it differently', { exact: true }).click()
            await submitFeedback(page)
        },
        retry: retryFeedback,
    },
    {
        kind: 'question' as const,
        submit: async (page: Page) => {
            const card = page.getByTestId('run-approval')
            await card.getByText('Example', { exact: true }).click()
            await card.getByText('Preview', { exact: true }).click()
            await card.getByRole('button', { name: 'Submit', exact: true }).click()
        },
        retry: async (page: Page) => {
            const card = page.getByTestId('run-approval')
            await expect(card.getByRole('checkbox', { name: /Example/ })).toBeChecked()
            await expect(card.getByRole('checkbox', { name: /Preview/ })).toBeChecked()
            await card.getByRole('button', { name: 'Submit', exact: true }).click()
        },
    },
    {
        kind: 'plan' as const,
        submit: async (page: Page) => {
            await page
                .getByTestId('run-approval')
                .getByText(/Enter to select/)
                .click()
            await page.keyboard.press('2')
            await submitFeedback(page)
        },
        retry: retryFeedback,
    },
]

test.describe('Startup and approvals', () => {
    test('startup exhaustion restores the draft for manual retry', async ({ page, surface }) => {
        await surface.open()
        await surface.emit(notification('_posthog/turn_complete'))
        await expect(page.getByTestId('sandbox-composer-send')).toBeDisabled()
        surface.status = 'completed'
        await page.reload()
        await expect(page.getByTestId('sandbox-composer-input')).toBeEditable()
        await page.getByTestId('posthog-ai-context-picker').click()
        await page.getByTestId('taxonomic-filter-searchfield').fill('synthetic_retry_event')
        await page.getByTestId('prop-filter-events-0').click()
        await page.keyboard.press('Escape')
        await expect(page.getByTestId('taxonomic-filter-searchfield')).toBeHidden()
        await expect(page.getByRole('button', { name: 'synthetic_retry_event', exact: true })).toBeVisible()
        const submissions: unknown[] = []
        let fail = true
        await page.route(/\/tasks\/[^/]+\/run\/$/, async (route) => {
            submissions.push(route.request().postDataJSON())
            await route.fulfill(
                fail
                    ? {
                          status: 503,
                          json: {
                              code: 'warm_run_activation_unavailable',
                              detail: 'Synthetic startup rejection',
                              retry_token: 'synthetic-retry-token',
                          },
                      }
                    : { json: surface.task() }
            )
        })
        await page.getByTestId('sandbox-composer-input').fill('Retry this synthetic message.')
        await page.getByTestId('sandbox-composer-send').click()
        await expect.poll(() => submissions.length).toBeGreaterThan(0)
        await page.clock.fastForward(20_001)
        await expect(page.getByTestId('sandbox-composer-input')).toHaveValue('Retry this synthetic message.')
        await expect(page.getByRole('button', { name: 'synthetic_retry_event', exact: true })).toBeVisible()
        await expect(page.getByTestId('sandbox-composer-send')).toBeEnabled()
        fail = false
        surface.status = 'in_progress'
        surface.runId = NEXT_RUN_ID
        await page.getByTestId('sandbox-composer-send').click()
        await surface.connected()
        await surface.emit(message('The manual retry completed.'), notification('_posthog/turn_complete'))
        await expect(page.getByText('The manual retry completed.', { exact: true })).toBeVisible()
        expect(submissions.at(-1)).toEqual(submissions[0])
    })

    for (const { kind, submit, retry: retryApproval } of approvalCases) {
        test(`${kind} approval reveals the composer and restores inputs after delivery failure`, async ({
            page,
            surface,
        }) => {
            await surface.open()
            await surface.emit(approval(kind))
            const card = page.getByTestId('run-approval')
            await expect(card).toBeVisible()
            await submit(page)
            const first = await surface.command(0)
            await expect(card).toBeHidden()
            await expect(page.getByTestId('sandbox-composer-input')).toBeEditable()
            await page.getByTestId('sandbox-composer-input').fill('Keep this separate draft.')
            await first.respond({ jsonrpc: '2.0', error: { code: -32000, message: 'Synthetic delivery failure' } })
            await expect(card).toBeVisible()
            await retryApproval(page)
            const retry = await surface.command(1)
            expect(retry.body).toEqual(first.body)
            await retry.respond()
            await expect(card).toBeHidden()
            await expect(page.getByTestId('sandbox-composer-input')).toHaveValue('Keep this separate draft.')
            expect(surface.commands).toHaveLength(2)
        })
    }
})
