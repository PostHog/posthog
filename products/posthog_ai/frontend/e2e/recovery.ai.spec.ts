import { expect } from '@playwright/test'

import { Provider, send, test } from './aiTest'

for (const provider of ['claude', 'codex'] as const) {
    test.describe(provider, () => {
        test.use({ provider })

        test('submission before workflow registration recovers the original run', async ({ ai, page }) => {
            const first = `First message ${ai.seed.id}`
            const followup = `Follow-up ${ai.seed.id}`
            await ai.configure([
                ai.text(first, 'First response received.', 1),
                ai.text(followup, 'Follow-up response received.', 2),
            ])
            const fault = ai.fault('registration')
            await fault.arm()
            await ai.open(page)
            await fault.waitUntilReached()
            await send(page, first)
            await ai.control('wait/not_found')
            await expect(page.getByText(first, { exact: true })).toBeVisible()
            await expect(page.getByTestId('run-startup-stop')).toBeVisible()
            await fault.release()
            await expect(page.getByText('First response received.', { exact: true })).toBeVisible()
            await ai.reconnectStream(page)
            await expect(page.getByText('First response received.', { exact: true })).toHaveCount(1)
            await send(page, followup)
            await expect(page.getByText('Follow-up response received.', { exact: true })).toBeVisible()
            await page.reload()
            await expect(page.getByText(first, { exact: true })).toHaveCount(1)
            await expect(page.getByText(followup, { exact: true })).toHaveCount(1)
            await expect(page.getByText('First response received.', { exact: true })).toHaveCount(1)
            await expect(page.getByText('Follow-up response received.', { exact: true })).toHaveCount(1)
            expect(await ai.snapshot()).toMatchObject({
                task_count: 1,
                run_count: 1,
                task_id: ai.seed.task_id,
                run_id: ai.seed.run_id,
            })
        })

        test('workflow waits for its worker and consumes a queued message once', async ({ ai, page }) => {
            const message = `Queued message ${ai.seed.id}`
            await ai.configure([ai.text(message, 'Queued response received.', 1)])
            const fault = ai.fault('worker')
            await fault.arm()
            await ai.open(page)
            await fault.waitUntilReached()
            await ai.control('wait/registered')
            await send(page, message)
            await ai.control('wait/accepted')
            await expect(page.getByText(message, { exact: true })).toBeVisible()
            await expect(page.getByText('Queued response received.', { exact: true })).toHaveCount(0)
            await fault.release()
            await expect(page.getByText('Queued response received.', { exact: true })).toBeVisible()
            await page.reload()
            await expect(page.getByText(message, { exact: true })).toHaveCount(1)
            await expect(page.getByText('Queued response received.', { exact: true })).toHaveCount(1)
            expect(await ai.snapshot()).toMatchObject({
                task_count: 1,
                run_count: 1,
                task_id: ai.seed.task_id,
                run_id: ai.seed.run_id,
            })
        })

        test('one approval survives a rejection before execution', async ({ ai, page }) => {
            const message = `Rename the seeded insight ${ai.seed.id}`
            const name = `Synthetic renamed insight ${ai.seed.id}`
            const callId = `call_${ai.seed.id}`
            const discoveryId = `discovery_${ai.seed.id}`
            const toolNames: Record<Provider, string> = { claude: 'mcp__posthog__exec', codex: 'exec' }
            await ai.configure([
                {
                    ...ai.text(message, '', 0),
                    fixture: provider === 'claude' ? 'insight-update' : 'tool-search',
                    substitutions: {
                        model: ai.seed.model,
                        message_id: `msg_${ai.seed.id}_0`,
                        tool_call_id: discoveryId,
                        tool_name: provider === 'claude' ? 'ToolSearch' : 'mcp__posthog__exec',
                        text: 'posthog exec',
                        arguments: JSON.stringify({ query: 'select:mcp__posthog__exec', max_results: 1 }),
                    },
                },
                {
                    ...ai.text(message, '', 1),
                    fixture: 'insight-update',
                    tool_result: { call_id: discoveryId, contains: 'posthog' },
                    substitutions: {
                        model: ai.seed.model,
                        message_id: `msg_${ai.seed.id}_1`,
                        tool_call_id: callId,
                        resource_id: String(ai.seed.insight_id),
                        tool_name: toolNames[provider],
                        ...(provider === 'codex' ? { tool_namespace: 'mcp__posthog' } : {}),
                        arguments: JSON.stringify({
                            command: `call posthog-connection-call ${JSON.stringify({
                                connection_id: ai.seed.connection_id,
                                tool: 'insight-update',
                                arguments: { id: ai.seed.insight_id, name },
                            })}`,
                        }),
                    },
                },
                {
                    ...ai.text(message, 'The seeded insight has been renamed.', 2),
                    tool_result: { call_id: callId, contains: name },
                },
            ])
            const fault = ai.fault('approval')
            await ai.open(page)
            await send(page, message)
            const allow = page.getByText(provider === 'claude' ? 'Yes' : 'Accept', { exact: true })
            await expect(allow).toBeVisible()
            await fault.arm()
            const rejection = page.waitForResponse(
                (response) => response.url().endsWith('/command/') && response.status() === 503
            )
            await allow.click()
            await fault.waitUntilReached()
            expect(await (await rejection).json()).toMatchObject({ code: 'agent_session_not_ready' })
            await expect(page.getByTestId('sandbox-composer-input')).toBeEditable()
            await expect(allow).toBeHidden()
            expect(await ai.snapshot()).toMatchObject({
                insight_name: 'Synthetic original insight',
                tool_executions: 0,
            })
            await fault.release()
            await expect(page.getByText('The seeded insight has been renamed.', { exact: true })).toBeVisible()
            await expect(allow).toHaveCount(0)
            const snapshot = await ai.snapshot()
            expect(snapshot).toMatchObject({
                insight_name: name,
                tool_executions: 1,
                task_count: 1,
                run_count: 1,
                task_id: ai.seed.task_id,
                run_id: ai.seed.run_id,
            })
            expect(
                snapshot.timeline.filter((event) => event.event === 'forwarded' && event.status === 200)
            ).toHaveLength(1)
        })
    })
}
