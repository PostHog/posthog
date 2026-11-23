import { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { notebookTestTemplate } from 'scenes/notebooks/Notebook/__mocks__/notebook-template-for-snapshot'
import {
    buildMarkdownNotebookContent,
    serializeMarkdownNotebookComponent,
} from 'scenes/notebooks/Notebook/markdownNotebookV2'
import type { NotebookVariable } from 'scenes/notebooks/Notebook/notebookVariables'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect, userEvent } from 'storybook/test'

import {
    appBuilderDemoCells,
    appBuilderDemoLayout as layout,
    appBuilderDemoResults,
    appBuilderDemoVariables,
} from './notebookAppBuilderFixtures'

const SHORT_ID = 'app-builder-demo'
const buildContent = (variables: NotebookVariable[]): ReturnType<typeof buildMarkdownNotebookContent> =>
    buildMarkdownNotebookContent(
        [
            '# Product weekly review',
            ...appBuilderDemoCells.map((cell) =>
                serializeMarkdownNotebookComponent('SQLV2', {
                    ...cell,
                    result: appBuilderDemoResults(variables)[cell.nodeId],
                })
            ),
        ].join('\n\n')
    )
const notebook = {
    ...notebookTestTemplate('Product weekly review', []),
    short_id: SHORT_ID,
    content: buildContent(appBuilderDemoVariables),
    app_revision: 1,
    app_draft: layout,
    app_published: layout,
    variables: appBuilderDemoVariables,
}
let runNumber = 0
let results = appBuilderDemoResults(appBuilderDemoVariables)
let saved = structuredClone(notebook)

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks/App builder',
    beforeEach: () => {
        saved = structuredClone(notebook)
        runNumber = 0
        results = appBuilderDemoResults(appBuilderDemoVariables)
    },
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.NOTEBOOK_APP_BUILDER, FEATURE_FLAGS.PHAI_SANDBOX_MODE],
        mockDate: '2026-10-19',
        pageUrl: `${urls.notebook(SHORT_ID)}?view=builder`,
        testOptions: {
            snapshotBrowsers: [],
            viewport: { width: 1800, height: 1200 },
            waitForSelector: '[data-attr="notebook-app-canvas"]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notebooks/kernel/compute_options': {
                    currency: 'USD',
                    presets: [],
                    allowed_cpu_cores: [1],
                    allowed_memory_gb: [2],
                    allowed_idle_timeout_seconds: [3600],
                },
                '/api/projects/:team_id/health_issues/summary': { results: [] },
                '/api/oauth/connected-apps': [],
                '/api/organizations/:id/product_push_campaign/active': () => [204, null],
                '/api/projects/:team_id/notebooks/app-builder-demo': () => [200, saved],
                '/api/projects/:team_id/notebooks/app-builder-demo/collab/stream': () => [503, {}],
                '/api/projects/:team_id/notebooks/app-builder-demo/kernel/status': {
                    backend: null,
                    status: 'stopped',
                    frames: [],
                },
                '/api/projects/:team_id/notebooks/app-builder-demo/sql_v2/runs/:run_id': ({ params }) => [
                    200,
                    {
                        status: 'done',
                        result: results[String(params.run_id).replace(/^\d+-/, '')],
                        error: null,
                    },
                ],
                '/api/projects/:team_id/notebooks/app-builder-demo/runs/:run_id': () => [
                    200,
                    {
                        run_id: String(runNumber),
                        status: 'done',
                        cell_count: appBuilderDemoCells.length,
                        current_index: appBuilderDemoCells.length,
                        cells: appBuilderDemoCells.map((cell) => ({
                            node_id: cell.nodeId,
                            run_id: runNumber + '-' + cell.nodeId,
                            status: 'done',
                            dataframe_name: cell.returnVariable,
                        })),
                    },
                ],
            },
            patch: {
                '/api/projects/:team_id/notebooks/app-builder-demo': async ({ request }) => {
                    const body = (await request.json()) as Partial<typeof notebook>
                    saved = { ...saved, ...body, app_revision: saved.app_revision + 1 }
                    return [200, saved]
                },
            },
            post: {
                '/api/projects/:team_id/notebooks/app-builder-demo/runs': async ({ request }) => {
                    const body = (await request.json()) as { variables: NotebookVariable[] }
                    saved = { ...saved, variables: body.variables, content: buildContent(body.variables) }
                    results = appBuilderDemoResults(body.variables)
                    runNumber++
                    return [
                        200,
                        { run_id: String(runNumber), cell_count: appBuilderDemoCells.length, starts_sandbox: false },
                    ]
                },
                '/api/projects/:team_id/file_system/home_folder': { id: 'home-folder', path: 'Home' },
                '/api/projects/:team_id/notebooks/app-builder-demo/collab/markdown_save': async ({ request }) => {
                    const body = (await request.json()) as { content: typeof notebook.content }
                    saved = {
                        ...saved,
                        content: body.content,
                        version: saved.version + 1,
                    }
                    return [200, saved]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj

export const Builder: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvas.getByLabelText('App components')).toBeVisible(), { timeout: 60000 })
        fireEvent.click(canvasElement.querySelector('[data-attr="notebook-app-add-text"]')!)
        await waitFor(() => expect(canvas.getByLabelText('Component text')).toBeVisible())
        fireEvent.change(canvas.getByLabelText('Component text'), {
            target: { value: '## Review notes\n\nAdded in the app builder.' },
        })
        const saveButton = canvasElement.querySelector('[data-attr="notebook-app-save"]')!
        await waitFor(() => expect(saveButton).toBeEnabled())
        fireEvent.click(saveButton)
        await waitFor(() => expect(saved.app_draft.blocks.at(-1)?.text).toContain('Review notes'))
        expect(saved.app_published.blocks).toHaveLength(layout.blocks.length)
    },
}

export const Published: Story = {
    parameters: { pageUrl: `${urls.notebook(SHORT_ID)}?view=app` },
    play: async ({ canvasElement }) => {
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="notebook-app-builder"]')).not.toBeNull(), {
            timeout: 60000,
        })
        const appElement = canvasElement.querySelector('[data-attr="notebook-app-builder"]') as HTMLElement
        const app = within(appElement)
        const metric = (value: string): Element | undefined =>
            [...appElement.querySelectorAll('.BoldNumber__value')].find((element) => element.textContent === value)
        await waitFor(() => expect(metric('1485')).toBeVisible(), {
            timeout: 60000,
        })
        expect(app.queryByRole('button', { name: 'Run' })).not.toBeInTheDocument()
        expect(app.queryByRole('tab', { name: 'Visualization' })).not.toBeInTheDocument()
        expect(app.queryByRole('tab', { name: 'Results' })).not.toBeInTheDocument()
        expect(app.queryByRole('button', { name: /export/i })).not.toBeInTheDocument()
        expect(appElement.querySelector('.MarkdownNotebook__component-header')).not.toBeInTheDocument()
        fireEvent.click(app.getByLabelText('Region', { exact: true }))
        fireEvent.click(await within(document.body).findByText('Europe', { exact: true }))
        fireEvent.change(app.getByRole('slider', { name: 'Lookback (weeks)' }), { target: { value: '2' } })
        const staleTags = await app.findAllByText('STALE', { exact: true })
        expect(staleTags).toHaveLength(3)
        for (const tag of staleTags) {
            expect(tag.closest('[data-attr="notebook-app-cell-header"]')).not.toBeNull()
        }
        const staleTag = staleTags[0]
        await userEvent.hover(staleTag)
        await waitFor(() =>
            expect(
                within(document.body).getByText('Inputs changed. Run all to update the charts and calculated values.')
            ).toBeVisible()
        )
        await userEvent.unhover(staleTag)
        fireEvent.click(appElement.querySelector('[data-attr="notebook-run-all"]') as HTMLElement)
        await waitFor(() => expect(metric('222')).toBeVisible(), {
            timeout: 60000,
        })
        await waitFor(() => expect(metric('64.9%')).toBeVisible())
        await waitFor(() => expect(app.queryAllByText('STALE', { exact: true })).toHaveLength(0))
        await waitFor(
            () =>
                expect(saved.content).toEqual(
                    expect.objectContaining({
                        content: expect.arrayContaining([
                            expect.objectContaining({
                                attrs: expect.objectContaining({ markdown: expect.stringContaining('1-growth-table') }),
                            }),
                        ]),
                    })
                ),
            { timeout: 10000 }
        )
        await userEvent.click(app.getByRole('button', { name: 'Open Signups in selected period in notebook' }))
        await waitFor(() => expect(canvasElement.querySelector('.MarkdownNotebook')).toBeVisible(), { timeout: 60000 })
        expect(canvasElement.querySelector('[data-attr="notebook-app-builder"]')).not.toBeInTheDocument()
        await waitFor(() =>
            expect(
                within(document.activeElement as HTMLElement).getByRole('textbox', { name: 'Output dataframe name' })
            ).toHaveValue('signup_total')
        )
    },
}
export const Notebook: Story = {
    parameters: { pageUrl: urls.notebook(SHORT_ID), testOptions: { waitForSelector: '.MarkdownNotebook' } },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvas.getByLabelText('Notebook options')).toBeVisible(), { timeout: 60000 })
        expect(canvas.queryByText('App builder')).not.toBeInTheDocument()
        await userEvent.click(canvas.getByLabelText('Notebook options'))
        const menu = within(document.body)
        await userEvent.click(await menu.findByText('App builder'))
        await waitFor(() => expect(canvas.getByLabelText('App components')).toBeVisible(), { timeout: 60000 })
        await userEvent.click(canvas.getByLabelText('More app actions'))
        await userEvent.click(await menu.findByText('Open notebook'))
        await waitFor(() => expect(canvasElement.querySelector('.MarkdownNotebook')).toBeVisible(), { timeout: 60000 })
        expect(canvas.queryByLabelText('App components')).not.toBeInTheDocument()
    },
}
export const FlagDisabled: Story = {
    parameters: { featureFlags: [], testOptions: { waitForSelector: '.MarkdownNotebook' } },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => expect(canvasElement.querySelector('.MarkdownNotebook')).toBeVisible(), { timeout: 60000 })
        expect(canvasElement.querySelector('[data-attr="notebook-app-builder"]')).not.toBeInTheDocument()
        await userEvent.click(canvas.getByLabelText('Notebook options'))
        await waitFor(() => expect(within(document.body).getByText('Duplicate', { exact: true })).toBeVisible())
        expect(within(document.body).queryByText('App builder')).not.toBeInTheDocument()
        router.actions.push(urls.notebook(SHORT_ID), { view: 'app' })
        await waitFor(() => expect(canvasElement.querySelector('.MarkdownNotebook')).toBeVisible(), { timeout: 60000 })
        expect(canvasElement.querySelector('[data-attr="notebook-app-builder"]')).not.toBeInTheDocument()
    },
}
export const Narrow: Story = { parameters: { testOptions: { viewport: { width: 1000, height: 1200 } } } }
