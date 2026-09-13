import { RUN_ID, approval, expect, message, notification, ready, test } from './runSurfaceTest'

test.describe('Cancellation, focus and history', () => {
    for (const navigate of [false, true]) {
        test(`startup Stop waits for the current prompt and clears on navigation=${navigate}`, async ({
            page,
            surface,
        }) => {
            surface.history = []
            const creation = await surface.holdCreation()
            await page.goto(`/project/${surface.teamId}/tasks/new`)
            await page.getByTestId('task-composer-input').fill('Start the synthetic task.')
            await page.getByTestId('task-composer-send').click()
            const request = await creation.request
            await expect(page.getByTestId('run-startup-stop')).toBeVisible()
            await page.getByTestId('run-startup-stop').click()
            await expect(page.getByTestId('run-startup-stop')).toBeDisabled()
            expect(surface.commands).toHaveLength(0)
            const finish = {
                stay: async () => {
                    await request.respond(surface.task())
                    await surface.connected()
                    await surface.emit(ready('previous-run'))
                    await expect(page.getByTestId('sandbox-composer-send')).toBeDisabled()
                    expect(surface.commands).toHaveLength(0)
                    await surface.emit(message('Start the synthetic task.', 'user'))
                    await expect(page.getByTestId('sandbox-composer-send')).toBeDisabled()
                    expect(surface.commands).toHaveLength(0)
                    await surface.emit(ready())
                    const cancel = await surface.command(0)
                    expect(cancel.runId).toBe(RUN_ID)
                    expect(cancel.body).toMatchObject({ method: 'cancel' })
                    await cancel.respond()
                    await surface.emit(notification('_posthog/turn_complete'))
                    await expect(page.getByTestId('sandbox-composer-input')).toBeEditable()
                    await page.getByTestId('sandbox-composer-input').fill('A follow-up after stopping.')
                    await expect(page.getByTestId('sandbox-composer-send')).toBeEnabled()
                    expect(surface.commands).toHaveLength(1)
                },
                leave: async () => {
                    await page.getByRole('link', { name: 'Activity', exact: true }).click()
                    await expect(page).toHaveURL(/\/activity\/explore/)
                    await request.respond(surface.task())
                    await expect(page).toHaveURL(/\/activity\/explore/)
                    await expect(page.getByTestId('run-startup-stop')).toBeHidden()
                    surface.history = [
                        ready(),
                        message('Start the synthetic task.', 'user'),
                        message('Working on the synthetic task.'),
                    ]
                    await surface.open()
                    await expect(page.getByTestId('sandbox-composer-input')).toBeEditable()
                    expect(surface.commands).toHaveLength(0)
                },
            }
            await finish[navigate ? 'leave' : 'stay']()
        })
    }

    test('Stop blocks conflicting actions and recovers from a failed cancellation', async ({ page, surface }) => {
        await surface.open()
        await surface.queue('Keep the saved direction.')
        await page.getByTestId('sandbox-composer-send').click()
        const first = await surface.command(0)
        expect(first.body).toMatchObject({ method: 'cancel' })
        await expect(page.getByTestId('sandbox-composer-send')).toBeDisabled()
        await expect(page.getByTestId('run-queue-steer')).toBeDisabled()
        await page.getByTestId('sandbox-composer-input').press('Escape')
        await surface.emit(approval())
        await expect(page.getByTestId('run-approval')).toBeHidden()
        expect(surface.commands).toHaveLength(1)
        await first.respond({ jsonrpc: '2.0', error: { code: -32000, message: 'Synthetic cancellation failure' } })
        await expect(page.getByTestId('run-approval')).toBeVisible()
        await page.getByTestId('run-approval').getByText('Allow', { exact: true }).click()
        await (await surface.command(1)).respond()
        await expect(page.getByTestId('sandbox-composer-send')).toBeEnabled()
        await page.getByTestId('sandbox-composer-send').click()
        const retry = await surface.command(2)
        expect(retry.body).toMatchObject({ method: 'cancel' })
        await retry.respond()
        await surface.emit(notification('_posthog/turn_complete'))
        await expect(page.getByTestId('sandbox-composer-input')).toBeEditable()
        await expect(page.getByText('Keep the saved direction.', { exact: true })).toBeVisible()
    })

    test('Escape respects a real context picker and queue editor before returning to the main chat', async ({
        page,
        surface,
    }) => {
        await surface.open()
        await surface.queue('Edit this saved direction.')
        await page.getByTestId('posthog-ai-context-picker').click()
        await expect(page.getByTestId('taxonomic-filter-searchfield')).toBeVisible()
        await page.keyboard.press('Escape')
        await expect(page.getByTestId('taxonomic-filter-searchfield')).toBeHidden()
        expect(surface.commands).toHaveLength(0)
        await page.getByText('Edit this saved direction.', { exact: true }).hover()
        await page.getByRole('button', { name: 'Edit message', exact: true }).click()
        const editor = page.getByTestId('run-queue-editor')
        await editor.getByRole('textbox').fill('An unfinished edit.')
        await editor.getByRole('textbox').press('Escape')
        await expect(editor).toBeVisible()
        expect(surface.commands).toHaveLength(0)
        await editor.getByRole('button', { name: 'Cancel', exact: true }).click()
        await expect(editor).toBeHidden()
        await page.getByText('Working on the synthetic task.', { exact: true }).click()
        await page.keyboard.press('Escape')
        await expect(page.getByText('Up next', { exact: true })).toBeHidden()
        const steer = await surface.command(0)
        expect(steer.body).toMatchObject({
            method: 'user_message',
            params: { content: 'Edit this saved direction.', steer: true },
        })
        await steer.respond()
        await expect(page.getByText('Up next', { exact: true })).toBeHidden()
    })

    for (const width of [1440, 780]) {
        test(`sidebar keeps startup draft and focus at viewport width ${width}`, async ({ page, surface }) => {
            await page.setViewportSize({ width, height: 1000 })
            const creation = await surface.holdCreation()
            await surface.openSidebar()
            await page.getByTestId('task-composer-input').fill('Start in the sidebar.')
            await page.getByTestId('task-composer-send').click()
            const request = await creation.request
            const startup = page.getByTestId('sandbox-composer-input')
            await expect(startup).toBeEditable()
            await startup.fill('Preserve this startup draft.')
            await expect(startup).toBeFocused()
            await request.respond(surface.task())
            await surface.connected()
            await surface.emit(
                ready(),
                message('Start in the sidebar.', 'user'),
                message('Working on the synthetic task.')
            )
            await expect(page.getByText('Working on the synthetic task.', { exact: true })).toBeVisible()
            await expect(page.getByTestId('sandbox-composer-input')).toHaveValue('Preserve this startup draft.')
            await expect(page.getByTestId('sandbox-composer-input')).toBeFocused()
            await page.getByText('Working on the synthetic task.', { exact: true }).click()
            await page.keyboard.press('Escape')
            await expect(page.getByTestId('sandbox-composer-input')).toHaveValue('Preserve this startup draft.')
            expect(surface.commands).toHaveLength(0)
            await page.getByTestId('sandbox-composer-input').press('Escape')
            const cancel = await surface.command(0)
            expect(cancel.body).toMatchObject({ method: 'cancel' })
            await cancel.respond()
            await surface.emit(notification('_posthog/turn_complete'))
            await expect(page.getByTestId('sandbox-composer-send')).toBeEnabled()
        })
    }

    test('reload and reconnect keep only the owning unresolved approval actionable', async ({ page, surface }) => {
        surface.history.push(
            notification('_posthog/run_started', { runId: 'previous-run' }, 'previous-run'),
            approval('permission', 'old-approval', 'previous-run'),
            notification('_posthog/run_started', { runId: RUN_ID }),
            approval('permission', 'current-approval')
        )
        await surface.open()
        const card = page.getByTestId('run-approval')
        await expect(card).toBeVisible()
        await page.reload()
        await surface.connected()
        await expect(card).toBeVisible()
        expect(surface.commands).toHaveLength(0)
        await surface.reconnect()
        await expect(card).toBeVisible()
        expect(surface.commands).toHaveLength(0)
        await surface.emit(notification('_posthog/permission_resolved', { requestId: 'current-approval' }))
        await expect(card).toBeHidden()
        await page.reload()
        await surface.connected()
        await expect(page.getByTestId('sandbox-composer-input')).toBeEditable()
        await expect(card).toBeHidden()
        expect(surface.commands).toHaveLength(0)
        await surface.emit(approval('permission', 'fresh-approval'))
        await card.getByText('Allow', { exact: true }).click()
        const command = await surface.command(0)
        expect(command.runId).toBe(RUN_ID)
        expect(command.body).toMatchObject({ params: { requestId: 'fresh-approval' } })
        await command.respond()
        await expect(card).toBeHidden()
    })
})
