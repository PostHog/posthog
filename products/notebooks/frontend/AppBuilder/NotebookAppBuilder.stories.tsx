import { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { notebookTestTemplate } from 'scenes/notebooks/Notebook/__mocks__/notebook-template-for-snapshot'
import {
    buildMarkdownNotebookContent,
    getMarkdownNotebookMarkdown,
    serializeMarkdownNotebookComponent,
} from 'scenes/notebooks/Notebook/markdownNotebookV2'
import type { NotebookVariable } from 'scenes/notebooks/Notebook/notebookVariables'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { AccessControlLevel } from '~/types'

import { expect, userEvent } from 'storybook/test'

import {
    appBuilderDemoCells,
    appBuilderDemoLayout as layout,
    appBuilderDemoResults,
    appBuilderDemoVariables,
} from './notebookAppBuilderFixtures'

const SHORT_ID = 'app-builder-demo'
const savedChartRun = '00000000-0000-4000-8000-000000000061'
const buildContent = (
    variables: NotebookVariable[],
    published = false
): ReturnType<typeof buildMarkdownNotebookContent> =>
    buildMarkdownNotebookContent(
        [
            '# Product weekly review',
            ...appBuilderDemoCells.map((cell) => {
                const result = appBuilderDemoResults(variables)[cell.nodeId]
                const hasSavedRun = published && cell.nodeId === 'weekly-signups'
                return serializeMarkdownNotebookComponent('SQLV2', {
                    ...cell,
                    ...(hasSavedRun ? { runId: savedChartRun } : {}),
                    result: hasSavedRun
                        ? { ...result, first_page: result.first_page.slice(0, 5), previewOnly: true, has_more: true }
                        : result,
                })
            }),
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
let failNextQuery = false

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks/App builder',
    beforeEach: () => {
        saved = structuredClone(notebook)
        failNextQuery = false
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
                '/api/projects/:team_id/notebooks/app-builder-demo/app_release': () => [
                    200,
                    {
                        revision: 1,
                        published_at: '2026-10-18T12:00:00Z',
                        results_as_of: '2026-10-18T09:00:00Z',
                        title: notebook.title,
                        layout,
                        markdown: getMarkdownNotebookMarkdown(buildContent(appBuilderDemoVariables, true)),
                        variables: appBuilderDemoVariables,
                        has_previous: false,
                    },
                ],
                [`/api/projects/:team_id/notebooks/app-builder-demo/sql_v2/runs/${savedChartRun}`]: () => {
                    const result = appBuilderDemoResults(appBuilderDemoVariables)['weekly-signups']
                    return [200, { status: 'done', result: { ...result, status: 'ok' }, rows: result.first_page }]
                },
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
                '/api/projects/:team_id/notebooks/app-builder-demo/app_preview': () => [
                    200,
                    { has_previous: true, problems: [], results_as_of: '2026-10-18T09:00:00Z' },
                ],
                '/api/projects/:team_id/notebooks/app-builder-demo/app_queries': async ({ request }) => {
                    const body = (await request.json()) as { variables: NotebookVariable[] }
                    return [
                        200,
                        appBuilderDemoCells.map((cell) => ({
                            node_id: cell.nodeId,
                            query: JSON.stringify({ nodeId: cell.nodeId, variables: body.variables }),
                        })),
                    ]
                },
                '/api/projects/:team_id/query/HogQLQuery': async ({ request }) => {
                    const body = (await request.json()) as { query: { query: string } }
                    if (!body.query.query.startsWith('{"nodeId":')) {
                        return [200, { results: [] }]
                    }
                    if (failNextQuery) {
                        failNextQuery = false
                        return [400, { detail: 'This query failed.' }]
                    }
                    const { nodeId, variables } = JSON.parse(body.query.query) as {
                        nodeId: string
                        variables: NotebookVariable[]
                    }
                    const result = appBuilderDemoResults(variables)[nodeId]
                    return [200, { columns: result.columns, types: result.types, results: result.first_page }]
                },
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

export const PublicationReview: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const review = await canvas.findByRole('button', { name: 'Review and publish' }, { timeout: 60000 })
        await userEvent.click(review)
        await waitFor(() => expect(canvas.getByText('Ready to publish')).toBeVisible())
        expect(canvas.getByText(/Oldest displayed result ran/)).toBeVisible()
        expect(canvas.getByRole('button', { name: 'Publish release' })).toBeEnabled()
        await userEvent.click(canvas.getByRole('button', { name: 'Restore previous release' }))
        const dialog = await within(document.body).findByRole('dialog')
        await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
        expect(saved.app_revision).toBe(1)
    },
}

export const Published: Story = {
    beforeEach: () => {
        saved.user_access_level = AccessControlLevel.Viewer
    },
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
        await waitFor(() => expect(metric('594')).toBeVisible(), { timeout: 10000 })
        fireEvent.click(app.getByLabelText('Auto-update results'))
        fireEvent.change(app.getByRole('slider', { name: 'Lookback (weeks)' }), { target: { value: '2' } })
        expect(metric('594')).toBeVisible()
        fireEvent.click(app.getByRole('button', { name: 'Apply filters' }))
        await waitFor(() => expect(metric('222')).toBeVisible(), {
            timeout: 60000,
        })
        await waitFor(() => expect(metric('64.9%')).toBeVisible())
        failNextQuery = true
        fireEvent.change(app.getByRole('slider', { name: 'Lookback (weeks)' }), { target: { value: '3' } })
        fireEvent.click(app.getByRole('button', { name: 'Apply filters' }))
        await app.findByText(/Could not update results/)
        expect(metric('222')).toBeVisible()

        const chart = app.getByRole('img', { name: /chart with 2 data series/i }).parentElement!
        const { left, top, width, height } = chart.getBoundingClientRect()
        const lastWeek = { clientX: left + width * 0.8, clientY: top + height * 0.5 }
        fireEvent.mouseMove(chart, lastWeek)
        await within(document.body).findByText('Filter the app by this value')
        fireEvent.click(chart, lastWeek)
        await waitFor(() => expect(app.getByLabelText('Starting week')).toHaveTextContent('October 12, 2026'))
        fireEvent.click(app.getByRole('button', { name: 'Apply filters' }))
        await waitFor(() => expect(metric('114')).toBeVisible(), { timeout: 10000 })

        expect(saved.variables).toEqual(appBuilderDemoVariables)
        expect(saved.content).toEqual(notebook.content)
        expect(runNumber).toBe(0)
        await userEvent.click(app.getByRole('button', { name: 'Open Signups in selected period in notebook' }))
        await waitFor(() => expect(canvasElement.querySelector('.MarkdownNotebook')).toBeVisible(), { timeout: 60000 })
        expect(canvasElement.querySelector('[data-attr="notebook-app-builder"]')).not.toBeInTheDocument()
        await waitFor(() =>
            expect(within(document.activeElement as HTMLElement).getByText('1485', { exact: true })).toBeVisible()
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
