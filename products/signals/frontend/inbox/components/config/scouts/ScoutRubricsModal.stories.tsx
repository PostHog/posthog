import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { ScoutRubricDocumentApi, ScoutRubricSaveApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutRubricsModal } from './ScoutRubricsModal'

const DOCUMENT: ScoutRubricDocumentApi = {
    config_id: 'example-scout-config',
    skill_name: 'signals-scout-example',
    revision: 0,
    criteria: [
        {
            id: 'default-evidence',
            title: 'Evidence supports the finding',
            description: 'Check that the finding is supported by evidence the scout inspected.',
            pass_condition:
                'Each conclusion follows from cited evidence. Uncertainty is stated when evidence is incomplete.',
            applicability: 'Runs that produce findings.',
            enabled: true,
            source: 'default',
        },
        {
            id: 'default-actionability',
            title: 'The finding has a useful next step',
            description: 'Check that a reader can decide what to do with a finding.',
            pass_condition: 'The report explains a concrete next step or why no action is needed.',
            applicability: 'Runs that produce findings intended to prompt action.',
            enabled: true,
            source: 'default',
        },
    ],
    generation: null,
}

const GENERATION: NonNullable<ScoutRubricDocumentApi['generation']> = {
    id: 'example-generation',
    status: 'completed',
    requested_at: '2026-09-01T10:00:00Z',
    completed_at: '2026-09-01T10:02:00Z',
    task_id: 'example-task',
    task_run_id: 'example-run',
    error: null,
    summary: 'The scout compares activity across time windows. These criteria check the scope of that comparison.',
    suggestions: [
        {
            id: 'custom-comparable-windows',
            title: 'Compare equivalent time windows',
            description: 'Check whether the comparison covers equally sized periods with the same filters.',
            pass_condition:
                'The compared periods have equal durations and use consistent filters, or the report explains a justified difference.',
            applicability: 'Runs that compare activity across periods.',
            enabled: true,
            source: 'custom',
        },
        {
            id: 'custom-supporting-counts',
            title: 'Include supporting counts',
            description: 'Check whether a reported percentage change includes the underlying counts.',
            pass_condition: 'The evidence includes the counts used to calculate the change.',
            applicability: 'Findings that describe a percentage change.',
            enabled: true,
            source: 'custom',
        },
    ],
}

const RUBRICS_URL = '/api/projects/:team_id/signals/scout/rubrics/:config_id/'

const meta: Meta<typeof ScoutRubricsModal> = {
    title: 'Scenes-App/Inbox/ScoutRubrics',
    component: ScoutRubricsModal,
    args: { teamId: 2, configId: DOCUMENT.config_id, scoutName: 'Activity change scout', onClose: () => {} },
    parameters: { layout: 'fullscreen', testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        mswDecorator({
            get: { [RUBRICS_URL]: () => [200, DOCUMENT] },
            put: {
                [RUBRICS_URL]: async ({ request }) => {
                    const data = (await request.json()) as ScoutRubricSaveApi
                    return [200, { ...DOCUMENT, ...data, revision: 1 }]
                },
            },
            post: {
                [`${RUBRICS_URL}generate/`]: () => [202, { ...DOCUMENT, generation: GENERATION }],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ScoutRubricsModal>

export const SharedDefaults: Story = {}

export const SuggestionsReady: Story = {
    decorators: [mswDecorator({ get: { [RUBRICS_URL]: () => [200, { ...DOCUMENT, generation: GENERATION }] } })],
}

export const Generating: Story = {
    decorators: [
        mswDecorator({
            get: {
                [RUBRICS_URL]: () => [
                    200,
                    {
                        ...DOCUMENT,
                        generation: { ...GENERATION, status: 'running', suggestions: [], completed_at: null },
                    },
                ],
            },
        }),
    ],
}

export const GenerationFailed: Story = {
    decorators: [
        mswDecorator({
            get: {
                [RUBRICS_URL]: () => [
                    200,
                    {
                        ...DOCUMENT,
                        generation: {
                            ...GENERATION,
                            status: 'failed',
                            suggestions: [],
                            error: 'The investigation could not finish. Try generating suggestions again.',
                        },
                    },
                ],
            },
        }),
    ],
}

export const LoadFailed: Story = {
    decorators: [
        mswDecorator({ get: { [RUBRICS_URL]: () => [503, { detail: 'Could not load rubrics. Try again.' }] } }),
    ],
}

export const Narrow: Story = {
    ...SuggestionsReady,
    parameters: { testOptions: { viewport: { width: 520, height: 900 }, waitForLoadersToDisappear: false } },
}
