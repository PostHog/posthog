import { expect } from '@playwright/test'

import { send, test } from './aiTest'

for (const provider of ['claude', 'codex'] as const) {
    test.describe(provider, () => {
        test.use({ provider })

        test('cold chat preserves the conversation through an idle follow-up', async ({ ai, page }) => {
            const prompt = `Describe the synthetic workspace ${ai.seed.id}.`
            await ai.configure([
                ai.text(prompt, 'The synthetic workspace is empty.', 1),
                ai.text('Suggest a first event.', 'Capture the example_opened event.', 2),
            ])
            await ai.open(page, { warm: false })
            expect(await ai.snapshot()).toMatchObject({ task_count: 0, run_count: 0 })
            await page.getByTestId('posthog-ai-context-picker').click()
            await page.getByTestId('taxonomic-filter-searchfield').fill('synthetic_workspace_opened')
            await page.getByTestId('prop-filter-events-0').click()
            await page.keyboard.press('Escape')
            await expect(page.getByTestId('taxonomic-filter-searchfield')).toBeHidden()
            await expect(page.getByRole('button', { name: 'synthetic_workspace_opened', exact: true })).toBeVisible()
            const creation = page.waitForRequest(
                (request) => new URL(request.url()).pathname.endsWith('/tasks/') && request.method() === 'POST'
            )
            await send(page, prompt)
            expect((await creation).postDataJSON().pending_user_message).toContain('synthetic_workspace_opened')
            await expect(page.getByText('The synthetic workspace is empty.', { exact: true })).toBeVisible()
            await expect(page.getByTestId('sandbox-composer-send')).toBeDisabled()
            const first = await ai.snapshot()
            const followup = page.waitForRequest(
                (request) => request.url().endsWith('/command/') && request.postDataJSON()?.method === 'user_message'
            )
            await send(page, 'Suggest a first event.')
            expect((await followup).postDataJSON().params.content).toBe('Suggest a first event.')
            await expect(page.getByText('Capture the example_opened event.', { exact: true })).toBeVisible()
            await page.reload()
            for (const text of [
                prompt,
                'The synthetic workspace is empty.',
                'Suggest a first event.',
                'Capture the example_opened event.',
            ]) {
                await expect(page.getByText(text, { exact: true })).toHaveCount(1)
            }
            expect(await ai.snapshot()).toMatchObject({
                task_id: first.task_id,
                run_id: first.run_id,
                task_count: 1,
                run_count: 1,
                runs: [{ state: { runtime_adapter: provider, model: ai.seed.model, initial_permission_mode: 'auto' } }],
            })
        })

        test('warm resume recovers on the intended successor with the original history', async ({ ai, page }) => {
            await ai.configure([
                ai.text('Remember the synthetic event example_opened.', 'I will remember example_opened.', 1),
                ai.text('Which event did we choose?', 'We chose example_opened.', 2),
            ])
            await ai.open(page)
            await send(page, 'Remember the synthetic event example_opened.')
            await expect(page.getByText('I will remember example_opened.', { exact: true })).toBeVisible()
            await expect(page.getByTestId('sandbox-composer-send')).toBeDisabled()
            const original = await ai.snapshot()
            await ai.control('complete_run')
            await page.reload()
            await expect(page.getByTestId('sandbox-composer-input')).toBeEditable()
            const registration = ai.fault('registration')
            await registration.arm()
            await ai.warmResume()
            await registration.waitUntilReached()
            expect(ai.seed.run_id).not.toBe(original.run_id)
            await send(page, 'Which event did we choose?')
            await ai.control('wait/not_found')
            await expect(page.getByText('Which event did we choose?', { exact: true })).toBeVisible()
            await registration.release()
            await expect(page.getByText('We chose example_opened.', { exact: true })).toBeVisible()
            await page.reload()
            for (const text of [
                'Remember the synthetic event example_opened.',
                'I will remember example_opened.',
                'Which event did we choose?',
                'We chose example_opened.',
            ]) {
                await expect(page.getByText(text, { exact: true })).toHaveCount(1)
            }
            expect(await ai.snapshot()).toMatchObject({
                task_id: original.task_id,
                run_id: ai.seed.run_id,
                task_count: 1,
                run_count: 2,
            })
        })
    })
}
