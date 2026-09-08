import { approval, expect, message, notification, test } from './runSurfaceTest'

test.describe('Queues and steering', () => {
    test('queue submission before the draft debounce clears the composer', async ({ page, surface }) => {
        await surface.open()
        await page.clock.pauseAt(new Date(Date.now() + 1_000))
        await page.getByTestId('sandbox-composer-input').fill('Save this pasted direction once.')
        await page.getByTestId('sandbox-composer-send').click()
        await expect(page.getByText('Up next', { exact: true })).toBeVisible()
        await expect(page.getByTestId('sandbox-composer-input')).toHaveValue('')
        await expect(page.getByText('Save this pasted direction once.', { exact: true })).toHaveCount(1)
        expect(surface.commands).toHaveLength(0)
    })

    for (const firstGate of ['approval', 'turn'] as const) {
        test(`queued follow-up waits for both gates when ${firstGate} finishes first`, async ({ page, surface }) => {
            await surface.open()
            await surface.emit(approval())
            await page.getByTestId('run-approval').getByText('Allow', { exact: true }).click()
            const permission = await surface.command(0)
            await surface.queue('Send this after the approved turn.')
            await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible()
            await expect(page.getByTestId('run-approval')).toHaveCount(1)
            const gates = {
                approval: async () => {
                    await permission.respond()
                    await expect(page.getByTestId('run-approval')).toHaveCount(0)
                },
                turn: async () => {
                    await surface.emit(notification('_posthog/turn_complete'))
                    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeHidden()
                },
            }
            await gates[firstGate]()
            await expect(page.getByText('Up next', { exact: true })).toBeVisible()
            expect(surface.commands).toHaveLength(1)
            await gates[firstGate === 'approval' ? 'turn' : 'approval']()
            const followup = await surface.command(1)
            expect(followup.body).toMatchObject({
                method: 'user_message',
                params: { content: 'Send this after the approved turn.' },
            })
            await followup.respond()
            await surface.emit(message('The queued follow-up completed.'), notification('_posthog/turn_complete'))
            await expect(page.getByText('The queued follow-up completed.', { exact: true })).toBeVisible()
            await expect(page.getByText('Up next', { exact: true })).toBeHidden()
            expect(surface.commands).toHaveLength(2)
        })
    }

    for (const trigger of ['button', 'Escape'] as const) {
        test(`${trigger} steers saved messages without sending the separate draft`, async ({ page, surface }) => {
            await surface.open()
            await surface.queue('First saved direction.')
            await surface.queue('Second saved direction.')
            await page.getByTestId('sandbox-composer-input').fill('This draft is not ready.')
            const steer = {
                button: () => page.getByTestId('run-queue-steer').click(),
                Escape: () => page.getByTestId('sandbox-composer-input').press('Escape'),
            }
            await steer[trigger]()
            const command = await surface.command(0)
            expect(command.body).toMatchObject({
                method: 'user_message',
                params: { content: 'First saved direction.\n\nSecond saved direction.', steer: true },
            })
            await command.respond()
            await surface.emit(message('The saved directions were received.'))
            await expect(page.getByText('The saved directions were received.', { exact: true })).toBeVisible()
            await expect(page.getByTestId('sandbox-composer-input')).toHaveValue('This draft is not ready.')
            await expect(page.getByText('Up next', { exact: true })).toBeHidden()
            expect(surface.commands).toHaveLength(1)
        })
    }

    for (const outcome of ['confirmed', 'failed'] as const) {
        test(`deferred steering handles ${outcome} approval delivery`, async ({ page, surface }) => {
            await surface.open()
            await surface.emit(approval())
            await page.getByTestId('run-approval').getByText('Allow', { exact: true }).click()
            const permission = await surface.command(0)
            await surface.queue('Steer after approval confirmation.')
            await page.getByTestId('run-queue-steer').click()
            await expect(page.getByTestId('run-queue-steer')).toBeDisabled()
            expect(surface.commands).toHaveLength(1)
            const resolve = {
                confirmed: async () => {
                    await permission.respond()
                    const steering = await surface.command(1)
                    expect(steering.body).toMatchObject({
                        method: 'user_message',
                        params: { content: 'Steer after approval confirmation.', steer: true },
                    })
                    await steering.respond()
                    await surface.emit(message('Deferred steering completed.'))
                    await expect(page.getByText('Deferred steering completed.', { exact: true })).toBeVisible()
                    await expect(page.getByText('Up next', { exact: true })).toBeHidden()
                    expect(surface.commands).toHaveLength(2)
                },
                failed: async () => {
                    await permission.respond({
                        jsonrpc: '2.0',
                        error: { code: -32000, message: 'Synthetic approval failure' },
                    })
                    await expect(page.getByTestId('run-approval')).toBeVisible()
                    await page.getByTestId('run-approval').getByText('Allow', { exact: true }).click()
                    await (await surface.command(1)).respond()
                    await expect(page.getByTestId('run-approval')).toHaveCount(0)
                    await expect(page.getByTestId('run-queue-steer')).toBeEnabled()
                    await expect(page.getByText('Up next', { exact: true })).toBeVisible()
                    expect(surface.commands).toHaveLength(2)
                },
            }
            await resolve[outcome]()
        })
    }

    test('failed queue delivery preserves order and supports explicit retry and editing', async ({ page, surface }) => {
        await surface.open()
        await surface.queue('Older saved direction.')
        await page.getByTestId('run-queue-steer').click()
        const failed = await surface.command(0)
        await failed.respond({ jsonrpc: '2.0', error: { code: -32000, message: 'Synthetic send failure' } })
        await expect(page.getByText('Up next', { exact: true })).toBeVisible()
        await surface.queue('Newer saved direction.')
        await page.getByTestId('run-queue-steer').click()
        const retry = await surface.command(1)
        expect(retry.body).toMatchObject({
            params: { content: 'Older saved direction.\n\nNewer saved direction.', steer: true },
        })
        await retry.respond({ jsonrpc: '2.0', error: { code: -32000, message: 'Synthetic send failure' } })
        await expect(page.getByText('Up next', { exact: true })).toBeVisible()
        await page.getByText('Older saved direction.\n\nNewer saved direction.', { exact: true }).hover()
        await page.getByRole('button', { name: 'Edit message', exact: true }).click()
        const editor = page.getByTestId('run-queue-editor')
        await editor.getByRole('textbox').fill('Edited saved direction.')
        await editor.getByRole('button', { name: 'Save', exact: true }).click()
        await expect(editor).toBeHidden()
        await expect(page.getByText('Edited saved direction.', { exact: true })).toBeVisible()
        await page.getByText('Edited saved direction.', { exact: true }).hover()
        await page.getByRole('button', { name: 'Remove from queue', exact: true }).click()
        await expect(page.getByText('Up next', { exact: true })).toBeHidden()
        expect(surface.commands).toHaveLength(2)
        await surface.queue('A fresh direction.')
        await surface.emit(notification('_posthog/turn_complete'))
        const fresh = await surface.command(2)
        expect(fresh.body).toMatchObject({ params: { content: 'A fresh direction.' } })
        await fresh.respond()
        await surface.emit(message('The fresh direction completed.'), notification('_posthog/turn_complete'))
        await expect(page.getByText('The fresh direction completed.', { exact: true })).toBeVisible()
    })

    test('Escape cancels an active turn when the saved queue is empty', async ({ page, surface }) => {
        await surface.open()
        await page.getByTestId('sandbox-composer-input').fill('Keep this unsent draft.')
        await page.getByTestId('sandbox-composer-input').press('Escape')
        const cancel = await surface.command(0)
        expect(cancel.body).toMatchObject({ method: 'cancel' })
        await expect(page.getByTestId('sandbox-composer-send')).toBeDisabled()
        await cancel.respond()
        await surface.emit(notification('_posthog/turn_complete'))
        await expect(page.getByTestId('sandbox-composer-send')).toBeEnabled()
        await expect(page.getByTestId('sandbox-composer-input')).toHaveValue('Keep this unsent draft.')
        expect(surface.commands).toHaveLength(1)
    })
})
