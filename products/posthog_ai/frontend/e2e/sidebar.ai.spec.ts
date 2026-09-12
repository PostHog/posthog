import { expect } from '@playwright/test'

import { send, test } from './aiTest'

test('sidebar SQL suggestions belong to the submitting editor across navigation and replay', async ({ ai, page }) => {
    const [editorA, editorB] = await ai.control<{ id: number; short_id: string; query: unknown }[]>('seed_editors')
    const first = `Revise the original editor ${ai.seed.id}.`
    const second = 'Prepare another change for this editor.'
    const queryA = 'SELECT 33 AS suggested_a'
    const lateQuery = 'SELECT 44 AS late_a'
    const firstResult = { call_id: `call_${ai.seed.id}_1`, contains: 'suggested_a' }
    await ai.configure([
        ai.discover(first),
        ai.exec(first, `call execute-sql ${JSON.stringify({ query: queryA })}`, 1, {
            call_id: `discovery_${ai.seed.id}`,
            contains: 'posthog',
        }),
        { ...ai.text(first, 'The first editor suggestion completed.', 2), tool_result: firstResult },
        ai.exec(second, `call execute-sql ${JSON.stringify({ query: lateQuery })}`, 3, firstResult),
        {
            ...ai.text(second, 'The delayed editor suggestion completed.', 4),
            tool_result: { call_id: `call_${ai.seed.id}_3`, contains: 'late_a' },
        },
    ])
    await ai.open(page)
    await page.goto(`/project/${ai.seed.team_id}/sql?open_insight=${editorA.short_id}#panel=max`)
    const editor = page.getByTestId('hogql-query-editor')
    await expect(editor).toContainText('original_a')
    await send(page, first)
    await expect(page.getByText('The first editor suggestion completed.', { exact: true })).toBeVisible()
    await expect(editor).toContainText('suggested_a')
    await page.getByRole('button', { name: 'Accept', exact: true }).click()
    const model = ai.fault('model')
    await model.arm('3')
    await send(page, second)
    await model.waitUntilReached()
    await page.getByRole('button', { name: 'Recents', exact: true }).click()
    await page.getByRole('link', { name: /^Synthetic editor B\b/ }).click({ timeout: 15_000 })
    await page.getByTestId('insight-edit-button').click()
    await expect(editor).toContainText('original_b')
    await model.release()
    await expect(page.getByText('The delayed editor suggestion completed.', { exact: true })).toBeVisible()
    await expect(editor).not.toContainText('late_a')
    await expect(page.getByRole('button', { name: 'Accept', exact: true })).toHaveCount(0)
    await page.goto(`/project/${ai.seed.team_id}/sql?open_insight=${editorB.short_id}#panel=max`)
    await page
        .getByTestId('task-open-history-preview')
        .filter({ hasText: 'Synthetic conversation' })
        .click({ timeout: 15_000 })
    await expect(editor).toContainText('original_b')
    await expect(page.getByText('The delayed editor suggestion completed.', { exact: true })).toHaveCount(1)
    await expect(editor).not.toContainText('late_a')
    const persisted = await page.request.get(`/api/projects/${ai.seed.team_id}/insights/${editorB.id}/`)
    expect(persisted.ok()).toBeTruthy()
    expect((await persisted.json()).query).toEqual(editorB.query)
    expect(await ai.snapshot()).toMatchObject({ task_count: 1, run_count: 1 })
})
