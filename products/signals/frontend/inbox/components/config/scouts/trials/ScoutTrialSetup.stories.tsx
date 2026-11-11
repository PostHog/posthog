import type { Meta, StoryObj } from '@storybook/react'

import type { ScoutRubricDocumentApi } from 'products/signals/frontend/generated/api.schemas'

import { scoutRubricReferenceFixture } from '../scoutRubricFixtures'
import { ScoutTrialSetup } from './ScoutTrialSetup'
import { trialFixtureLongReport, trialFixtureSetup } from './scoutTrialsFixtures'
import { initialTrialVariants } from './scoutTrialUtils'

const noop = (): void => {}
const variants = initialTrialVariants(trialFixtureSetup)
variants[1] = {
    ...variants[1],
    label: 'Shorter prompt',
    replacePrompt: true,
    prompt: 'Find recurring checkout failures. Verify the evidence, then report the most useful next step.',
}
variants.push({ ...variants[0], id: 'higher-effort', label: 'Higher effort', effort: 'high' })

const rubric: ScoutRubricDocumentApi = {
    config_id: trialFixtureSetup.config_id,
    skill_name: trialFixtureSetup.skill_name,
    revision: 2,
    criteria: trialFixtureLongReport.criteria.map((criterion) => ({
        ...criterion,
        enabled: true,
        source: 'custom',
    })),
    generation: null,
    reference_context: scoutRubricReferenceFixture,
    reference_generation_id: 'example-rubric-generation',
}

const meta: Meta<typeof ScoutTrialSetup> = {
    title: 'Scenes-App/Inbox/Scout trials/Setup',
    component: ScoutTrialSetup,
    args: {
        setup: trialFixtureSetup,
        variants,
        repeats: 2,
        note: '',
        batch: null,
        submitting: false,
        totalRuns: 6,
        formError: null,
        trialsDisabledReason: null,
        hasUnaccepted: false,
        rubric,
        rubricLoading: false,
        rubricError: null,
        onViewRubric: noop,
        onReloadRubric: noop,
        onBack: noop,
        updateVariant: noop,
        addVariant: noop,
        removeVariant: noop,
        setRepeats: noop,
        setNote: noop,
        submitComparison: noop,
    },
    parameters: { layout: 'padded', testOptions: { waitForLoadersToDisappear: false } },
}
export default meta
type Story = StoryObj<typeof ScoutTrialSetup>

export const Default: Story = {}

export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
}

export const RunLimit: Story = {
    args: { variants: variants.slice(0, 2), repeats: 20, totalRuns: 40 },
}

export const UnsavedRubric: Story = {
    args: { rubric: { ...rubric, revision: 0, reference_context: null, reference_generation_id: null } },
}

export const LoadingRubric: Story = {
    args: { rubric: null, rubricLoading: true },
}

export const RubricError: Story = {
    args: { rubric: null, rubricError: 'Could not load the saved rubric. Try again.' },
}
