import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { notebookTestTemplate } from 'scenes/notebooks/Notebook/__mocks__/notebook-template-for-snapshot'
import { buildMarkdownNotebookContent } from 'scenes/notebooks/Notebook/markdownNotebookV2'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect } from 'storybook/test'

const RESULT = {
    columns: ['month', 'orgs'],
    types: [
        ['month', 'Date'],
        ['orgs', 'UInt64'],
    ],
    row_count: 6,
    first_page: [
        ['2023-01-01', 120],
        ['2023-02-01', 180],
        ['2023-03-01', 150],
        ['2023-04-01', 240],
        ['2023-05-01', 310],
        ['2023-06-01', 290],
    ],
    has_more: false,
}

const sqlCellTag = (display: string, id: string): string =>
    `<SQLV2 nodeId="${id}" title="Orgs by month" hideInput={true} showFilters={false} code="select month, orgs from monthly_orgs" returnVariable="sql_df" outputTab="visualization" vizQuery={${JSON.stringify(
        {
            kind: 'DataVisualizationNode',
            display,
            chartSettings: { xAxis: { column: 'month' }, yAxis: [{ column: 'orgs' }] },
        }
    )}} runId="run-1" result={${JSON.stringify(RESULT)}} />`

const demoMarkdown = `# Weekly product review

Compare acquisition and activation with notes next to each chart.

<Columns widths={[2, 1]}>

<Column>

## Acquisition

New organizations grew through the first half of the year.

${sqlCellTag('ActionsBar', 'demo-acquisition')}

</Column>

<Column>

## Activation

The latest month needs a closer look.

${sqlCellTag('ActionsLineGraph', 'demo-activation')}

- Review onboarding
- Compare signup sources

</Column>

</Columns>

## Next steps

This paragraph spans the full notebook width.`

const notebooks = {
    'columns-demo': {
        ...notebookTestTemplate('Weekly product review', []),
        content: buildMarkdownNotebookContent(demoMarkdown),
    },
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Notebooks/Columns',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-07-04',
        featureFlags: [FEATURE_FLAGS.REVAMPED_PY_NOTEBOOKS],
        testOptions: {
            waitForSelector: '.MarkdownNotebook__columns .DataVisualization canvas',
            snapshotBrowsers: [],
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notebooks/:short_id/sql_v2/runs/:run_id': {
                    status: 'done',
                    result: RESULT,
                    error: null,
                },
                '/api/projects/:team_id/notebooks/kernel/compute_options': {
                    currency: 'USD',
                    cpu_rate_per_core_hour: 0.2,
                    memory_rate_per_gb_hour: 0.025,
                    default_preset_key: 'small',
                    presets: [
                        {
                            key: 'small',
                            name: 'Small',
                            description: 'Exploring data and working with small dataframes.',
                            cpu_cores: 1,
                            memory_gb: 2,
                            hourly_price: 0.25,
                        },
                    ],
                    allowed_cpu_cores: [1],
                    allowed_memory_gb: [2],
                    allowed_idle_timeout_seconds: [3600],
                },
                '/api/projects/:team_id/notebooks/:short_id': ({ params }) => [
                    200,
                    { ...notebooks[params.short_id as keyof typeof notebooks], short_id: params.short_id },
                ],
            },
            post: {
                '/api/projects/:team_id/file_system/home_folder/': { id: 'home-folder', path: 'Home' },
                '/api/projects/:team_id/notebooks/:short_id/collab/markdown_save': async ({ params, request }) => {
                    const body = (await request.json()) as Record<string, unknown> & { version: number }
                    return {
                        ...notebooks[params.short_id as keyof typeof notebooks],
                        short_id: params.short_id,
                        ...body,
                        version: body.version + 1,
                    }
                },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<{}>

// Opening the notebook autosaves it, and the "Saved" tag shows for 3 s of real time, so wait it out.
const waitForAutosaveTag: Story['play'] = async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await waitFor(() => expect(canvas.queryByText('Saved')).not.toBeNull(), { timeout: 3000 }).catch(() => undefined)
    await waitFor(() => expect(canvas.queryByText('Saved')).toBeNull(), { timeout: 5000 })
}

export const TextAndCharts: Story = {
    parameters: { pageUrl: urls.notebook('columns-demo') },
    play: waitForAutosaveTag,
}
