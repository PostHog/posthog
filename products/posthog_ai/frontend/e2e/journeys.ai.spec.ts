import { expect } from '@playwright/test'

import { send, test } from './aiTest'

for (const provider of ['claude', 'codex'] as const) {
    test.describe(provider, () => {
        test.use({ provider })

        test('an accepted-consent deep link submits once and keeps the conversation usable', async ({ ai, page }) => {
            const prompt = `Describe the synthetic deep link ${ai.seed.id}.`
            await ai.configure([
                ai.text(prompt, 'The deep link reached this conversation.', 1),
                {
                    ...ai.text('Continue this conversation.', 'The follow-up reached the same conversation.', 2),
                    history_contains: ['The deep link reached this conversation.'],
                },
            ])
            await ai.open(page, {
                warm: false,
                path: `/project/${ai.seed.team_id}/ai?ask=${encodeURIComponent(prompt)}`,
            })
            await expect(page.getByText('The deep link reached this conversation.', { exact: true })).toBeVisible()
            await send(page, 'Continue this conversation.')
            await expect(page.getByText('The follow-up reached the same conversation.', { exact: true })).toBeVisible()
            await page.reload()
            for (const text of [
                prompt,
                'The deep link reached this conversation.',
                'Continue this conversation.',
                'The follow-up reached the same conversation.',
            ]) {
                await expect(page.getByText(text, { exact: true })).toHaveCount(1)
            }
            expect(await ai.snapshot()).toMatchObject({ task_count: 1, run_count: 1 })
        })

        for (const phase of ['startup', 'active turn'] as const) {
            test(`real ${phase} Stop cancels the owning turn and accepts a follow-up`, async ({ ai, page }) => {
                const prompt = `Start cancellable work ${ai.seed.id}.`
                const discovery = { call_id: `discovery_${ai.seed.id}`, contains: 'posthog' }
                const followup = ai.text('Continue after stopping.', 'The follow-up after stopping completed.', 2)
                await ai.configure(
                    phase === 'startup'
                        ? [ai.text(prompt, 'This cancelled response must never appear.', 0), followup]
                        : [
                              ai.discover(prompt),
                              ai.exec(
                                  prompt,
                                  `call insight-create ${JSON.stringify({
                                      name: `Cancelled insight ${ai.seed.id}`,
                                      query: {
                                          kind: 'DataVisualizationNode',
                                          display: 'ActionsTable',
                                          source: { kind: 'HogQLQuery', query: 'SELECT 99 AS cancelled_value' },
                                      },
                                  })}`,
                                  1,
                                  discovery
                              ),
                              { ...followup, tool_result: discovery },
                          ]
                )
                const model = ai.fault('model')
                await model.arm(phase === 'startup' ? '0' : '1')
                const worker = ai.fault('worker')
                if (phase === 'startup') {
                    await worker.arm()
                }
                await ai.open(page)
                await send(page, prompt)
                const cancellation = page.waitForResponse(
                    (response) =>
                        response.url().endsWith('/command/') && response.request().postDataJSON()?.method === 'cancel'
                )
                if (phase === 'startup') {
                    await worker.waitUntilReached()
                    await page.getByTestId('run-startup-stop').click()
                    await expect(page.getByTestId('run-startup-stop')).toBeDisabled()
                    expect(
                        (await ai.snapshot()).timeline.filter((event) => event.event === 'cancel_forwarded')
                    ).toHaveLength(0)
                    await worker.release()
                } else {
                    await model.waitUntilReached()
                    await page.getByRole('button', { name: 'Stop', exact: true }).click()
                }
                await model.waitUntilReached()
                expect((await cancellation).ok()).toBeTruthy()
                await model.release()
                await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeHidden()
                await send(page, 'Continue after stopping.')
                await expect(page.getByText('The follow-up after stopping completed.', { exact: true })).toBeVisible()
                await page.reload()
                await expect(page.getByText('This cancelled response must never appear.', { exact: true })).toHaveCount(
                    0
                )
                await expect(page.getByText(prompt, { exact: true })).toHaveCount(1)
                await expect(page.getByText('Continue after stopping.', { exact: true })).toHaveCount(1)
                await expect(page.getByText('The follow-up after stopping completed.', { exact: true })).toHaveCount(1)
                const snapshot = await ai.snapshot()
                expect(snapshot).toMatchObject({ task_count: 1, run_count: 1, tool_executions: 0 })
                const insights = await page.request.get(`/api/projects/${ai.seed.team_id}/insights/`)
                expect(insights.ok()).toBeTruthy()
                expect((await insights.json()).results).toHaveLength(0)
                expect(snapshot.timeline.filter((event) => event.event === 'cancel_forwarded')).toEqual([
                    expect.objectContaining({ run_id: snapshot.run_id, status: 200 }),
                ])
            })
        }
    })
}
