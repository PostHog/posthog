import { useActions, useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { getEffortLabel, getModelLabel } from 'products/posthog_ai/frontend/utils/composerModels'

import { taskAnalysisSceneLogic } from '../logics/taskAnalysisSceneLogic'
import type { AIRunPreferenceDraft } from '../utils/aiRunPreferenceDraft'
import { AIRunPreferenceEditor } from './AIRunPreferenceEditor'

function describeTarget(modelLabel: string, draft: AIRunPreferenceDraft): string {
    return draft.reasoning_effort ? `${modelLabel} at ${getEffortLabel(draft.reasoning_effort)} effort` : modelLabel
}

export function TaskAnalysisSettings(): JSX.Element {
    const { catalogue, draft, draftDirty, preferencesLoading } = useValues(taskAnalysisSceneLogic)
    const { setDraft, submitDraft } = useActions(taskAnalysisSceneLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    // The pick applies to every later analysis run of the project, and one run reads a whole task
    // run, so a wrong pick can multiply the cost before anybody looks at this page again.
    const confirmAndSave = (): void => {
        const target = draft.model
            ? describeTarget(getModelLabel(catalogue, draft.model), draft)
            : 'the built-in analysis model'
        LemonDialog.open({
            title: draft.model ? 'Change the analysis model?' : 'Go back to the built-in analysis model?',
            description: `Every new analysis run in this project will use ${target}. Each run reads a full task run, so the cost of analysis can change a lot. Runs that are in progress keep their current model.`,
            primaryButton: {
                children: 'Change model',
                'data-attr': 'task-analysis-model-confirm',
                onClick: submitDraft,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <section className="flex flex-col gap-2">
            <p className="text-secondary mb-0">
                Analysis runs review finished task runs. Pick the model they use, or keep the built-in one.
            </p>
            <AIRunPreferenceEditor
                draft={draft}
                dirty={draftDirty}
                saving={preferencesLoading}
                inheritLabel="Built-in analysis model"
                onChange={setDraft}
                onSave={confirmAndSave}
                restrictionReason={restrictionReason}
                dataAttrPrefix="task-analysis-model"
            />
            {restrictionReason ? <p className="text-secondary mb-0">Only project admins can change this.</p> : null}
        </section>
    )
}
