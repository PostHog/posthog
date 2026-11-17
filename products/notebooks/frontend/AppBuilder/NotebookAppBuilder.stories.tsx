import { Meta, StoryObj } from '@storybook/react'
import { fireEvent, waitFor, within } from '@testing-library/dom'

import { App } from 'scenes/App'
import { notebookTestTemplate } from 'scenes/notebooks/Notebook/__mocks__/notebook-template-for-snapshot'
import {
    buildMarkdownNotebookContent,
    serializeMarkdownNotebookComponent,
} from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect } from 'storybook/test'

import type { NotebookAppLayoutApi } from '../generated/api.schemas'

const SHORT_ID = 'app-builder-demo'
const result = {
    columns: ['week', 'signups', 'activated'],
    types: [
        ['week', 'Date'],
        ['signups', 'UInt64'],
        ['activated', 'UInt64'],
    ],
    row_count: 6,
    first_page: [
        ['2026-09-07', 120, 84],
        ['2026-09-14', 160, 112],
        ['2026-09-21', 145, 104],
        ['2026-09-28', 210, 157],
        ['2026-10-05', 250, 190],
        ['2026-10-12', 285, 223],
    ],
}
const markdown = [
    '# Product weekly review',
    serializeMarkdownNotebookComponent('SQLV2', {
        nodeId: 'weekly-signups',
        title: 'Signups and activation',
        code: 'select week, signups, activated from weekly_growth',
        returnVariable: 'weekly_growth',
        outputTab: 'visualization',
        runId: 'demo-run',
        result,
        vizQuery: {
            kind: 'DataVisualizationNode',
            display: 'ActionsLineGraph',
            chartSettings: { xAxis: { column: 'week' }, yAxis: [{ column: 'signups' }, { column: 'activated' }] },
        },
    }),
    serializeMarkdownNotebookComponent('SQLV2', {
        nodeId: 'growth-table',
        title: 'Weekly breakdown',
        code: 'select * from weekly_growth',
        returnVariable: 'growth_table',
        result,
    }),
    serializeMarkdownNotebookComponent('PythonV2', {
        nodeId: 'total-signups',
        title: 'Signups this week',
        code: 'weekly_growth.signups.iloc[-1]',
        result: { columns: [], row_count: 0, result_text: '285' },
    }),
].join('\n\n')
const layout: NotebookAppLayoutApi = {
    title: 'Product weekly review',
    description: 'Explore acquisition and activation. Adjust the inputs, then run the notebook to refresh the results.',
    full_width: true,
    tabs: [
        { id: 'overview', title: 'Overview' },
        { id: 'details', title: 'Data and methodology' },
    ],
    blocks: [
        {
            id: 'region',
            kind: 'input',
            tab_id: 'overview',
            width: 4,
            variable: 'region',
            title: 'Region',
            input_kind: 'select',
            options: ['All regions', 'North America', 'Europe'],
        },
        {
            id: 'window',
            kind: 'input',
            tab_id: 'overview',
            width: 4,
            variable: 'weeks',
            title: 'Lookback (weeks)',
            input_kind: 'slider',
            min: 1,
            max: 12,
            step: 1,
        },
        {
            id: 'include',
            kind: 'input',
            tab_id: 'overview',
            width: 4,
            variable: 'include_trials',
            title: 'Include trial accounts',
            input_kind: 'auto',
        },
        {
            id: 'trend',
            kind: 'cell',
            tab_id: 'overview',
            width: 8,
            node_id: 'weekly-signups',
            title: 'Acquisition and activation',
            display: 'output',
        },
        {
            id: 'context',
            kind: 'text',
            tab_id: 'overview',
            width: 4,
            text: '## This week\n\n**285** new signups\n\n**78%** activation rate\n\nActivation means completing the first project setup.\n\n### What to explore\n\n- Compare regions with the input above\n- Extend the lookback to spot trends\n- Open the data tab for the full breakdown',
        },
        {
            id: 'table',
            kind: 'cell',
            tab_id: 'details',
            width: 12,
            node_id: 'growth-table',
            title: 'Weekly breakdown',
            display: 'both',
        },
        {
            id: 'methodology',
            kind: 'text',
            tab_id: 'details',
            width: 12,
            text: '## Methodology\n\nWeeks start on Monday. Trial accounts are included by default. Queries and definitions live in the source notebook.',
        },
    ],
}
const notebook = {
    ...notebookTestTemplate('Product weekly review', []),
    short_id: SHORT_ID,
    content: buildMarkdownNotebookContent(markdown),
    app_revision: 1,
    app_draft: layout,
    app_published: layout,
    variables: [
        { name: 'region', type: 'string', value: 'All regions' },
        { name: 'weeks', type: 'number', value: 6 },
        { name: 'include_trials', type: 'boolean', value: true },
    ],
}
let saved = structuredClone(notebook)

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks/App builder',
    beforeEach: () => {
        saved = structuredClone(notebook)
    },
    parameters: {
        layout: 'fullscreen',
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
                '/api/projects/:team_id/notebooks/app-builder-demo/kernel/status': {
                    backend: null,
                    status: 'stopped',
                    frames: [],
                },
                '/api/projects/:team_id/notebooks/app-builder-demo/sql_v2/runs/:run_id': {
                    status: 'done',
                    result,
                    error: null,
                },
            },
            patch: {
                '/api/projects/:team_id/notebooks/app-builder-demo': async ({ request }) => {
                    const body = (await request.json()) as Partial<typeof notebook>
                    saved = { ...saved, ...body, app_revision: saved.app_revision + 1 }
                    return [200, saved]
                },
            },
            post: {
                '/api/projects/:team_id/file_system/home_folder': { id: 'home-folder', path: 'Home' },
                '/api/projects/:team_id/notebooks/app-builder-demo/collab/markdown_save': async ({ request }) => {
                    const body = (await request.json()) as Partial<typeof notebook>
                    saved = { ...saved, ...body, version: saved.version + 1 }
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
        await waitFor(() => expect(canvas.getByRole('complementary', { name: 'App components' })).toBeVisible())
        fireEvent.click(canvasElement.querySelector('[data-attr="notebook-app-add-text"]')!)
        await waitFor(() => expect(canvas.getByRole('textbox', { name: 'Component text' })).toBeVisible())
        fireEvent.change(canvas.getByRole('textbox', { name: 'Component text' }), {
            target: { value: '## Review notes\n\nAdded in the app builder.' },
        })
        fireEvent.click(canvas.getByRole('button', { name: 'Save draft' }))
        await waitFor(() => expect(saved.app_draft.blocks.at(-1)?.text).toContain('Review notes'))
        expect(saved.app_published.blocks).toHaveLength(layout.blocks.length)
    },
}

export const Published: Story = { parameters: { pageUrl: `${urls.notebook(SHORT_ID)}?view=app` } }
export const Notebook: Story = {
    parameters: { pageUrl: urls.notebook(SHORT_ID), testOptions: { waitForSelector: '.MarkdownNotebook' } },
}
export const Narrow: Story = { parameters: { testOptions: { viewport: { width: 1000, height: 1200 } } } }
