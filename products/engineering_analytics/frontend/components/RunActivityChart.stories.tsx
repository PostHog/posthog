import type { Meta, StoryObj } from '@storybook/react'

import { RunActivityChart, type ActivityRun } from './RunActivityChart'

const RUNS: ActivityRun[] = [
    { runId: 1001, conclusion: 'success', startedAt: '2026-07-10T08:00:00Z', durationSeconds: 720 },
    { runId: 1002, conclusion: 'success', startedAt: '2026-07-10T08:10:00Z', durationSeconds: 1080 },
    { runId: 1003, conclusion: 'failure', startedAt: '2026-07-10T08:20:00Z', durationSeconds: 2700 },
    { runId: 1004, conclusion: 'success', startedAt: '2026-07-10T08:30:00Z', durationSeconds: 840 },
    { runId: 1005, conclusion: 'success', startedAt: '2026-07-10T08:40:00Z', durationSeconds: 1320 },
    { runId: 1006, conclusion: 'timed_out', startedAt: '2026-07-10T09:00:00Z', durationSeconds: 4200 },
    { runId: 1007, conclusion: 'success', startedAt: '2026-07-10T09:20:00Z', durationSeconds: 960 },
    { runId: 1008, conclusion: 'failure', startedAt: '2026-07-10T09:30:00Z', durationSeconds: 1980 },
    { runId: 1009, conclusion: 'success', startedAt: '2026-07-10T09:50:00Z', durationSeconds: 1140 },
    { runId: 1010, conclusion: 'success', startedAt: '2026-07-10T10:00:00Z', durationSeconds: 780 },
    { runId: 1011, conclusion: 'failure', startedAt: '2026-07-10T10:10:00Z', durationSeconds: 3300 },
    { runId: 1012, conclusion: 'success', startedAt: '2026-07-10T10:30:00Z', durationSeconds: 900 },
    { runId: 1013, conclusion: 'success', startedAt: '2026-07-10T11:00:00Z', durationSeconds: 1500 },
    { runId: 1014, conclusion: 'failure', startedAt: '2026-07-10T11:10:00Z', durationSeconds: 2400 },
    { runId: 1015, conclusion: 'success', startedAt: '2026-07-10T11:30:00Z', durationSeconds: 1020 },
    { runId: 1016, conclusion: 'success', startedAt: '2026-07-10T12:00:00Z', durationSeconds: 1260 },
]

const meta: Meta<typeof RunActivityChart> = {
    title: 'Scenes-App/Engineering Analytics/Run Activity Chart',
    component: RunActivityChart,
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-07-10T13:00:00Z',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '[data-attr="run-activity-chart-story"] svg',
            viewport: { width: 1280, height: 520 },
        },
    },
    decorators: [
        (Story) => (
            <div className="p-6" data-attr="run-activity-chart-story">
                <Story />
            </div>
        ),
    ],
    args: {
        runs: RUNS,
    },
}

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}
