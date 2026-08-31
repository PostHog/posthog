import type { Meta, StoryObj } from '@storybook/react'

import type { Series } from '@posthog/quill-charts'

import { ReplayVisionClassifierVisualizationPrototype } from './ReplayVisionClassifierVisualizationPrototype'

const DATE_LABELS = [
    '2026-06-08',
    '2026-06-15',
    '2026-06-22',
    '2026-06-29',
    '2026-07-06',
    '2026-07-13',
    '2026-07-20',
    '2026-07-27',
    '2026-08-03',
    '2026-08-10',
    '2026-08-17',
    '2026-08-24',
]

const TIMELINE_DATE_LABELS = [
    'Jun 8',
    'Jun 15',
    'Jun 22',
    'Jun 29',
    'Jul 6',
    'Jul 13',
    'Jul 20',
    'Jul 27',
    'Aug 3',
    'Aug 10',
    'Aug 17',
    'Aug 24',
]

const USE_CASE_SERIES: Series[] = [
    {
        key: 'investigate-incidents',
        label: 'Investigate incidents',
        data: [42, 40, 39, 38, 37, 35, 33, 32, 31, 30, 29, 28],
        fill: { opacity: 0.45 },
    },
    {
        key: 'monitor-health',
        label: 'Monitor service health',
        data: [25, 27, 28, 29, 30, 30, 31, 31, 32, 31, 30, 29],
        fill: { opacity: 0.45 },
    },
    {
        key: 'compare-releases',
        label: 'Compare releases',
        data: [8, 9, 10, 10, 12, 13, 15, 17, 19, 21, 23, 24],
        fill: { opacity: 0.45 },
    },
    {
        key: 'configure-alerts',
        label: 'Configure alerts',
        data: [10, 11, 10, 11, 10, 11, 10, 11, 10, 10, 9, 10],
        fill: { opacity: 0.45 },
    },
    {
        key: 'share-reports',
        label: 'Share status reports',
        data: [12, 14, 14, 15, 15, 16, 16, 16, 15, 15, 14, 13],
        fill: { opacity: 0.45 },
    },
    {
        key: 'automate-triage',
        label: 'Automate triage',
        data: [0, 0, 0, 0, 0, 2, 4, 7, 11, 15, 18, 22],
        fill: { opacity: 0.45 },
    },
    {
        key: 'inconclusive',
        label: 'Inconclusive',
        data: [5, 4, 5, 4, 5, 5, 5, 5, 5, 5, 5, 4],
        fill: { opacity: 0.45 },
    },
]

const CHANGE_SERIES: Series[] = [
    { key: 'investigate-incidents', label: 'Investigate incidents', data: [30, 23] },
    { key: 'monitor-health', label: 'Monitor service health', data: [27, 24] },
    { key: 'compare-releases', label: 'Compare releases', data: [13, 17] },
    { key: 'configure-alerts', label: 'Configure alerts', data: [9, 8] },
    { key: 'share-reports', label: 'Share status reports', data: [14, 11] },
    { key: 'automate-triage', label: 'Automate triage', data: [3, 13] },
    { key: 'inconclusive', label: 'Inconclusive', data: [4, 4] },
]

const WEEKLY_TOTALS = DATE_LABELS.map((_, index) =>
    USE_CASE_SERIES.reduce((total, useCase) => total + (useCase.data[index] ?? 0), 0)
)
const TIMELINE_SERIES = [...USE_CASE_SERIES].reverse()
const TIMELINE_CATEGORY_LABELS = TIMELINE_SERIES.map((useCase) => useCase.label)
const TIMELINE_CELLS = TIMELINE_SERIES.map((useCase) =>
    useCase.data.map((count, index) => Math.round((count / WEEKLY_TOTALS[index]) * 100))
)

const meta: Meta<typeof ReplayVisionClassifierVisualizationPrototype> = {
    title: 'Replay Vision/Explorations/Classifier visualizations',
    component: ReplayVisionClassifierVisualizationPrototype,
    decorators: [
        (Story) => (
            <div className="min-h-screen bg-bg-light p-6">
                <Story />
            </div>
        ),
    ],
    parameters: { layout: 'fullscreen' },
    args: {
        initialVisualization: 'volume',
        dateLabels: DATE_LABELS,
        series: USE_CASE_SERIES,
        changeLabels: ['Previous 4 weeks', 'Current 4 weeks'],
        changeSeries: CHANGE_SERIES,
        timelineDateLabels: TIMELINE_DATE_LABELS,
        timelineCategoryLabels: TIMELINE_CATEGORY_LABELS,
        timelineCells: TIMELINE_CELLS,
        observationCount: 1382,
        configuredCategoryCount: 6,
        discoveredCategory: 'Automate triage',
        discoveredCategoryDate: 'July 13',
    },
}

export default meta

type Story = StoryObj<typeof ReplayVisionClassifierVisualizationPrototype>

export const Volume: Story = {}

export const Share: Story = { args: { initialVisualization: 'share' } }

export const Change: Story = { args: { initialVisualization: 'change' } }

export const Timeline: Story = { args: { initialVisualization: 'timeline' } }
