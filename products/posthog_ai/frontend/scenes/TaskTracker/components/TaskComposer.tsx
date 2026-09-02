import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import {
    Composer,
    DEFAULT_SUGGESTIONS_DATA,
    type SuggestionItem,
    Suggestions,
    Welcome,
} from 'products/posthog_ai/frontend/api/primitives'
import { modelCatalogueLogic } from 'products/posthog_ai/frontend/logics/modelCatalogueLogic'
import { getRuntimeAdapterForModel, resolveEffortForModel } from 'products/posthog_ai/frontend/utils/composerModels'
import {
    cycleMode,
    getModesForRuntimeAdapter,
    resolveModeForRuntimeAdapter,
} from 'products/posthog_ai/frontend/utils/composerModes'

import { AttachedContextBar } from '../../../components/composer/AttachedContextBar'
import { ComposerModelEffortPickers } from '../../../components/composer/ComposerModelEffortPickers'
import { ComposerModePicker } from '../../../components/composer/ComposerModePicker'
import { ComposerModeShortcut } from '../../../components/composer/ComposerModeShortcut'
import { useDebouncedDraft } from '../../../components/composer/useDebouncedDraft'
import { OnboardingReplayButton } from '../../../components/onboarding/OnboardingReplayButton'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { RepositorySelector } from './RepositorySelector'

export function TaskComposer(): JSX.Element {
    const { submitNewTask, setNewTaskData, setActiveSuggestionGroup, applySuggestion, clearConsentBlock } =
        useActions(taskTrackerSceneLogic)
    const { newTaskData, isSubmittingTask, activeSuggestionGroup, displayHeadline, consentBlocked } =
        useValues(taskTrackerSceneLogic)
    const { catalogue } = useValues(modelCatalogueLogic)
    // Permission modes belong to the harness, so they follow the picked model.
    const composerAdapter = getRuntimeAdapterForModel(catalogue, newTaskData.model)

    // The bound instance's key — 'scene' on `/ai` and `/tasks`, the panel key when embedded. The onboarding
    // takeover is keyed the same way, so a starter prompt chosen on replay reaches this composer.
    const panelId = useMountedLogic(taskTrackerSceneLogic).props.panelId

    // Buffer the description locally and debounce the write to kea so each keystroke is a cheap, isolated
    // re-render instead of a store dispatch. `Composer.Root` already blocks send on an empty `draft.value`
    // internally, so there's no need to pass a `disabledReason` derived from the logic's debounced value.
    const draft = useDebouncedDraft(newTaskData.description, (value) => setNewTaskData({ description: value }))

    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    const handleSelectSuggestion = (item: SuggestionItem): void => {
        applySuggestion(item)
        if (item.requiresUserInput) {
            textAreaRef.current?.focus()
        }
    }

    return (
        <div className="flex flex-col h-full min-h-0 items-center justify-center overflow-y-auto p-4">
            <div className="w-full max-w-2xl flex flex-col items-center gap-4">
                <Welcome headline={displayHeadline}>
                    {/* Temporary migration affordance — delete with the rest of the onboarding takeover
                        once everyone is on the new PostHog AI. */}
                    <OnboardingReplayButton panelId={panelId} />
                </Welcome>

                <Suggestions.Root
                    activeGroup={activeSuggestionGroup}
                    onActiveGroupChange={setActiveSuggestionGroup}
                    onSelectSuggestion={handleSelectSuggestion}
                    onNavigate={(url) => router.actions.push(url)}
                >
                    {/* Repo/branch picker sits 8px above the input it configures. */}
                    <div className="w-full flex flex-col gap-2">
                        <RepositorySelector
                            value={newTaskData.repositoryConfig}
                            onChange={(config) => setNewTaskData({ repositoryConfig: config })}
                        />
                        <ComposerModeShortcut
                            onCycle={() =>
                                setNewTaskData({
                                    permissionMode: cycleMode(composerAdapter, newTaskData.permissionMode),
                                })
                            }
                        />
                        <Composer.Root
                            value={draft.value}
                            onChange={draft.onChange}
                            onSubmit={() => draft.submit(submitNewTask)}
                            loading={isSubmittingTask}
                            textAreaRef={textAreaRef}
                        >
                            <Composer.Frame>
                                <Composer.Header>
                                    <AttachedContextBar />
                                </Composer.Header>
                                <Composer.Field>
                                    <Composer.Placeholder>Describe the task in detail…</Composer.Placeholder>
                                    <Composer.Textarea autoFocus data-attr="task-composer-input" />
                                </Composer.Field>
                                <Composer.Footer className="flex flex-wrap items-center gap-1 pl-2">
                                    <ComposerModePicker
                                        modes={getModesForRuntimeAdapter(composerAdapter)}
                                        selectedMode={newTaskData.permissionMode}
                                        onModeChange={(permissionMode) => setNewTaskData({ permissionMode })}
                                    />
                                    <ComposerModelEffortPickers
                                        models={catalogue}
                                        selectedModel={newTaskData.model}
                                        selectedEffort={newTaskData.reasoningEffort}
                                        onModelChange={(model) =>
                                            setNewTaskData({
                                                model,
                                                reasoningEffort: resolveEffortForModel(
                                                    catalogue,
                                                    newTaskData.reasoningEffort,
                                                    model
                                                ),
                                                // Clamp the mode too, not just the effort: leaving a
                                                // Claude-only mode selected against a Codex model would
                                                // show one permission ceiling and send a broader one.
                                                permissionMode: resolveModeForRuntimeAdapter(
                                                    getRuntimeAdapterForModel(catalogue, model),
                                                    newTaskData.permissionMode
                                                ),
                                            })
                                        }
                                        onEffortChange={(reasoningEffort) => setNewTaskData({ reasoningEffort })}
                                    />
                                </Composer.Footer>
                            </Composer.Frame>
                            <Suggestions.Dropdown />
                            <AIConsentPopoverWrapper
                                placement="bottom-end"
                                showArrow
                                ignoreDismissal
                                hidden={!consentBlocked}
                                onApprove={() => submitNewTask()}
                                onDismiss={() => clearConsentBlock()}
                            >
                                <Composer.Submit data-attr="task-composer-send" />
                            </AIConsentPopoverWrapper>
                        </Composer.Root>
                    </div>

                    <Suggestions.Buttons data={DEFAULT_SUGGESTIONS_DATA} />
                </Suggestions.Root>
            </div>
        </div>
    )
}
