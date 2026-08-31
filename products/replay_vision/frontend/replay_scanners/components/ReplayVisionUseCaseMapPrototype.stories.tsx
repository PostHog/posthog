import type { Meta, StoryObj } from '@storybook/react'

import type { Series } from '@posthog/quill-charts'

import { ReplayVisionUseCaseMapPrototype, type UseCaseChange } from './ReplayVisionUseCaseMapPrototype'

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

const USE_CASE_SERIES: Series[] = [
    {
        key: 'investigate-incidents',
        label: 'Investigate incidents',
        data: [42, 40, 39, 38, 37, 35, 33, 32, 31, 30, 29, 28],
    },
    {
        key: 'monitor-health',
        label: 'Monitor service health',
        data: [25, 27, 28, 29, 30, 30, 31, 31, 32, 31, 30, 29],
    },
    {
        key: 'compare-releases',
        label: 'Compare releases',
        data: [8, 9, 10, 10, 12, 13, 15, 17, 19, 21, 23, 24],
    },
    {
        key: 'configure-alerts',
        label: 'Configure alerts',
        data: [10, 11, 10, 11, 10, 11, 10, 11, 10, 10, 9, 10],
    },
    {
        key: 'share-reports',
        label: 'Share status reports',
        data: [12, 14, 14, 15, 15, 16, 16, 16, 15, 15, 14, 13],
    },
    {
        key: 'automate-triage',
        label: 'Automate triage',
        data: [0, 0, 0, 0, 0, 2, 4, 7, 11, 15, 18, 22],
    },
    {
        key: 'inconclusive',
        label: 'Inconclusive',
        data: [5, 4, 5, 4, 5, 5, 5, 5, 5, 5, 5, 4],
    },
]

const CHANGES: UseCaseChange[] = [
    {
        key: 'automate-triage',
        label: 'Automate triage',
        direction: 'new',
        source: 'freeform',
        currentShare: 17,
        percentagePointChange: null,
        currentSessionCount: 22,
        firstObservedAt: '2026-07-13',
        firstObservedLabel: 'July 13',
        evidence: [
            {
                recordingId: 'prototype-recording-automation-1',
                summary:
                    'The user grouped repeated failures, assigned an owner, and scheduled the same triage workflow to run again.',
                timestampLabel: '03:18',
                timestampMs: 198000,
                confidence: 0.94,
            },
            {
                recordingId: 'prototype-recording-automation-2',
                summary:
                    'The user created an incident rule, linked it to a team, and returned to the queue to confirm that the rule ran.',
                timestampLabel: '05:42',
                timestampMs: 342000,
                confidence: 0.91,
            },
        ],
    },
    {
        key: 'compare-releases',
        label: 'Compare releases',
        direction: 'growing',
        source: 'configured',
        currentShare: 18,
        percentagePointChange: 5,
        currentSessionCount: 24,
        evidence: [
            {
                recordingId: 'prototype-recording-releases-1',
                summary:
                    'The user opened two releases, compared their error groups, and filtered the change to one service.',
                timestampLabel: '02:07',
                timestampMs: 127000,
                confidence: 0.9,
            },
            {
                recordingId: 'prototype-recording-releases-2',
                summary:
                    'The user moved between release markers and incident details before sharing the comparison with a teammate.',
                timestampLabel: '04:36',
                timestampMs: 276000,
                confidence: 0.87,
            },
        ],
    },
    {
        key: 'investigate-incidents',
        label: 'Investigate incidents',
        direction: 'fading',
        source: 'configured',
        currentShare: 22,
        percentagePointChange: -7,
        currentSessionCount: 28,
        evidence: [
            {
                recordingId: 'prototype-recording-incidents-1',
                summary:
                    'The user opened an incident, inspected the timeline and affected service, then added a note with the likely cause.',
                timestampLabel: '01:51',
                timestampMs: 111000,
                confidence: 0.93,
            },
            {
                recordingId: 'prototype-recording-incidents-2',
                summary:
                    'The user searched for a failure, narrowed it by environment, and closed the incident after checking its latest occurrence.',
                timestampLabel: '06:12',
                timestampMs: 372000,
                confidence: 0.89,
            },
        ],
    },
]

const meta: Meta<typeof ReplayVisionUseCaseMapPrototype> = {
    title: 'Replay Vision/Explorations/Use case map',
    component: ReplayVisionUseCaseMapPrototype,
    decorators: [
        (Story) => (
            <div className="min-h-screen bg-bg-light p-6">
                <Story />
            </div>
        ),
    ],
    parameters: { layout: 'fullscreen' },
    args: {
        productName: 'Incident Hub',
        dateLabels: DATE_LABELS,
        series: USE_CASE_SERIES,
        changes: CHANGES,
        observedSessionCount: 1382,
        highConfidenceShare: 83,
        comparisonWeeks: 4,
        onOpenRecording: () => undefined,
        onPromoteUseCase: () => undefined,
    },
}

export default meta

type Story = StoryObj<typeof ReplayVisionUseCaseMapPrototype>

export const Default: Story = {}
