import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { mswDecorator } from '~/mocks/browser'

import type { ScoutRubricDocumentApi, ScoutRubricSaveApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutRubricReferenceFixture } from './scoutRubricFixtures'
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
    reference_context: null,
    reference_generation_id: null,
}

const GENERATION: NonNullable<ScoutRubricDocumentApi['generation']> = {
    id: 'example-generation',
    status: 'completed',
    context: '',
    requested_at: '2026-09-01T10:00:00Z',
    completed_at: '2026-09-01T10:02:00Z',
    task_id: 'example-task',
    task_run_id: 'example-run',
    error: null,
    reference_context: scoutRubricReferenceFixture,
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

const SAVED_DOCUMENT: ScoutRubricDocumentApi = {
    ...DOCUMENT,
    revision: 3,
    criteria: [
        {
            id: 'custom-segment',
            title: 'Check which users are affected before describing a change across the whole product',
            description:
                'Look at the relevant segments and explain whether the change affects everyone or a smaller group.',
            pass_condition:
                'The report names the affected segment, gives its activity counts, and distinguishes its change from the overall trend.',
            applicability: 'Runs that find a change concentrated in one segment.',
            enabled: true,
            source: 'custom',
        },
        ...DOCUMENT.criteria,
    ],
}

const RUBRICS_URL = '/api/projects/:team_id/signals/scout/rubrics/:config_id/'

const meta: Meta<typeof ScoutRubricsModal> = {
    title: 'Scenes-App/Inbox/ScoutRubrics',
    component: ScoutRubricsModal,
    args: { teamId: 2, configId: DOCUMENT.config_id, scoutName: 'Activity change scout', onClose: () => {} },
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-09-01T10:01:24Z',
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: { [RUBRICS_URL]: () => [200, DOCUMENT] },
            put: {
                [RUBRICS_URL]: async ({ request }) => {
                    const data = (await request.json()) as ScoutRubricSaveApi
                    return [
                        200,
                        {
                            ...DOCUMENT,
                            ...data,
                            revision: 1,
                            reference_context: data.adopt_generation_id ? scoutRubricReferenceFixture : null,
                            reference_generation_id: data.adopt_generation_id ?? null,
                            generation: GENERATION,
                        },
                    ]
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

export const WithFocus: Story = {
    play: async ({ canvasElement }) => {
        const modal = within(canvasElement.ownerDocument.body)
        await userEvent.click(await modal.findByText('Additional focus'))
        await userEvent.type(
            await modal.findByLabelText('What should suggestions pay extra attention to?'),
            'Please emphasize whether comparisons use consistent filters and enough data.'
        )
    },
}

export const SuggestionsReady: Story = {
    decorators: [mswDecorator({ get: { [RUBRICS_URL]: () => [200, { ...SAVED_DOCUMENT, generation: GENERATION }] } })],
}

export const SuggestionsSelected: Story = {
    ...SuggestionsReady,
    play: async ({ canvasElement }) => {
        const modal = within(canvasElement.ownerDocument.body)
        await userEvent.click(await modal.findByText('Select all'))
    },
}

export const EditingSuggestion: Story = {
    ...SuggestionsReady,
    play: async ({ canvasElement }) => {
        const modal = within(canvasElement.ownerDocument.body)
        await userEvent.click(await modal.findByLabelText('Edit Compare equivalent time windows'))
        await userEvent.type(await modal.findByLabelText('Description'), ' Include the same weekdays in each period.')
    },
}

export const ReferenceWithoutSuggestions: Story = {
    decorators: [
        mswDecorator({
            get: { [RUBRICS_URL]: () => [200, { ...DOCUMENT, generation: { ...GENERATION, suggestions: [] } }] },
        }),
    ],
}

export const SavedReference: Story = {
    decorators: [
        mswDecorator({
            get: {
                [RUBRICS_URL]: () => [
                    200,
                    {
                        ...DOCUMENT,
                        revision: 1,
                        reference_context: scoutRubricReferenceFixture,
                        reference_generation_id: GENERATION.id,
                    },
                ],
            },
        }),
    ],
}

export const DetailsExpanded: Story = {
    ...SuggestionsReady,
    play: async ({ canvasElement }) => {
        const modal = within(canvasElement.ownerDocument.body)
        await userEvent.click(await modal.findByLabelText('Show details for Compare equivalent time windows'))
        await userEvent.click(await modal.findByLabelText('Show details for Evidence supports the finding'))
    },
}

export const Generating: Story = {
    decorators: [
        mswDecorator({
            get: {
                [RUBRICS_URL]: () => [
                    200,
                    {
                        ...SAVED_DOCUMENT,
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
