import { expect } from '@playwright/test'

import { send, test } from './aiTest'

for (const provider of ['claude', 'codex'] as const) {
    test.describe(provider, () => {
        test.use({ provider })

        test('a real insight tool renders query rows and opens the persisted insight after reload', async ({
            ai,
            page,
        }) => {
            const prompt = `Create the synthetic table ${ai.seed.id}.`
            const name = `Synthetic result table ${ai.seed.id}`
            const query = {
                kind: 'DataVisualizationNode',
                display: 'ActionsTable',
                source: { kind: 'HogQLQuery', query: "SELECT 'synthetic_alpha' AS label, 7 AS total" },
            }
            await ai.configure([
                ai.discover(prompt),
                ai.exec(prompt, `call insight-create ${JSON.stringify({ name, query })}`, 1, {
                    call_id: `discovery_${ai.seed.id}`,
                    contains: 'posthog',
                }),
                {
                    ...ai.text(prompt, 'The synthetic table is saved.', 2),
                    tool_result: { call_id: `call_${ai.seed.id}_1`, contains: name },
                },
            ])
            await ai.open(page)
            await send(page, prompt)
            await expect(page.getByText('The synthetic table is saved.', { exact: true })).toBeVisible()
            const response = await page.request.get(
                `/api/projects/${ai.seed.team_id}/insights/?search=${encodeURIComponent(name)}`
            )
            expect(response.ok()).toBeTruthy()
            const saved = (await response.json()).results
            expect(saved).toHaveLength(1)
            expect(saved[0]).toMatchObject({ name, query })
            const row = page.getByRole('row').filter({ has: page.getByText('synthetic_alpha', { exact: true }) })
            await expect(row).toContainText('7')
            await page.getByRole('button', { name: 'Hide visualization', exact: true }).click()
            await expect(row).toBeHidden()
            await page.getByRole('button', { name: 'Show visualization', exact: true }).click()
            await expect(row).toContainText('7')
            await page.reload()
            await expect(row).toHaveCount(1)
            await expect(row).toContainText('7')
            const opened = page.waitForEvent('popup')
            await page.locator(`a[href$="/insights/${saved[0].short_id}"]`).click({ timeout: 15_000 })
            const insight = await opened
            await expect(insight).toHaveURL(new RegExp(`/insights/${saved[0].short_id}`))
            await expect(
                insight.getByRole('row').filter({ has: insight.getByText('synthetic_alpha', { exact: true }) })
            ).toContainText('7')
            await insight.close()
            expect(await ai.snapshot()).toMatchObject({ task_count: 1, run_count: 1 })
        })
    })
}
