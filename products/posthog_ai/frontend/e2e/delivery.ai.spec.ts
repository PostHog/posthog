import { expect } from '@playwright/test'

import { send, test } from './aiTest'

for (const provider of ['claude', 'codex'] as const) {
    test.describe(provider, () => {
        test.use({ provider })

        for (const delivery of ['queue', 'steer'] as const) {
            test(`real ${delivery} preserves saved message order through approval confirmation`, async ({
                ai,
                page,
            }) => {
                const prompt = `Rename the connected insight ${ai.seed.id}.`
                const name = `Synthetic approved rename ${ai.seed.id}`
                const first = 'First saved direction.'
                const second = 'Second saved direction.'
                const queued = `${first}\n\n${second}`
                const result = { call_id: `call_${ai.seed.id}_1`, contains: name }
                await ai.configure([
                    ai.discover(prompt),
                    ai.exec(
                        prompt,
                        `call posthog-connection-call ${JSON.stringify({
                            connection_id: ai.seed.connection_id,
                            tool: 'insight-update',
                            arguments: { id: ai.seed.insight_id, name },
                        })}`,
                        1,
                        { call_id: `discovery_${ai.seed.id}`, contains: 'posthog' }
                    ),
                    { ...ai.text(prompt, 'The approved rename completed.', 2), tool_result: result },
                    { ...ai.text(queued, 'Both saved directions arrived in order.', 3), tool_result: result },
                ])
                const confirmation = ai.fault('approval_confirmation')
                const model = ai.fault('model')
                await confirmation.arm()
                await model.arm('2')
                await ai.open(page)
                await send(page, prompt)
                await page.getByText(provider === 'claude' ? 'Yes' : 'Accept', { exact: true }).click()
                await confirmation.waitUntilReached()
                await model.waitUntilReached()
                for (const [index, message] of [first, second].entries()) {
                    await send(page, message)
                    await expect(page.getByText(index === 0 ? first : queued, { exact: true })).toBeVisible()
                    await expect(page.getByTestId('sandbox-composer-input')).toHaveValue('')
                }
                await page.getByTestId('sandbox-composer-input').fill('Keep this separate draft.')
                const commands: { params: { content: string; steer?: boolean } }[] = []
                page.on('request', (request) => {
                    if (request.url().endsWith('/command/') && request.postDataJSON()?.method === 'user_message') {
                        commands.push(request.postDataJSON())
                    }
                })
                if (delivery === 'steer') {
                    await page.getByTestId('run-queue-steer').click()
                    await expect(page.getByTestId('run-queue-steer')).toBeDisabled()
                }
                expect(commands).toHaveLength(0)
                expect(await ai.snapshot()).toMatchObject({ insight_name: name, tool_executions: 1 })
                await confirmation.release()
                if (delivery === 'queue') {
                    await expect(page.getByTestId('run-approval')).toHaveCount(0)
                    expect(commands).toHaveLength(0)
                }
                await model.release()
                await expect(page.getByText('Both saved directions arrived in order.', { exact: true })).toBeVisible()
                await expect(page.getByTestId('sandbox-composer-input')).toHaveValue('Keep this separate draft.')
                await expect(page.getByText('Up next', { exact: true })).toBeHidden()
                expect(commands).toHaveLength(1)
                expect(commands[0].params.content).toBe(queued)
                expect(commands[0].params.steer === true).toBe(delivery === 'steer')
                await page.reload()
                await expect(page.locator('p').filter({ hasText: /^(First|Second) saved direction\.$/ })).toHaveText([
                    first,
                    second,
                ])
                await expect(page.getByText('Both saved directions arrived in order.', { exact: true })).toHaveCount(1)
                expect(await ai.snapshot()).toMatchObject({
                    insight_name: name,
                    tool_executions: 1,
                    task_count: 1,
                    run_count: 1,
                })
            })
        }
    })
}
