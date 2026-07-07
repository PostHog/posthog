import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import {
    Composer,
    DEFAULT_SUGGESTIONS_DATA,
    type SuggestionItem,
    Suggestions,
    Welcome,
} from 'products/posthog_ai/frontend/api/primitives'
import { resolveEffortForModel } from 'products/posthog_ai/frontend/utils/composerModels'

import { AttachedContextBar } from '../../../components/composer/AttachedContextBar'
import { ComposerModelEffortPickers } from '../../../components/composer/ComposerModelEffortPickers'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { RepositorySelector } from './RepositorySelector'

export function TaskComposer(): JSX.Element {
    const { submitNewTask, setNewTaskData, setActiveSuggestionGroup, applySuggestion } =
        useActions(taskTrackerSceneLogic)
    const { newTaskData, isSubmittingTask, activeSuggestionGroup, headline, sendDisabledReason } =
        useValues(taskTrackerSceneLogic)

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
                <Welcome headline={headline} />

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
                        <Composer.Root
                            value={newTaskData.description}
                            onChange={(value) => setNewTaskData({ description: value })}
                            onSubmit={submitNewTask}
                            loading={isSubmittingTask}
                            disabledReason={sendDisabledReason}
                            textAreaRef={textAreaRef}
                        >
                            <Composer.Frame>
                                <Composer.Header>
                                    <AttachedContextBar />
                                </Composer.Header>
                                <Composer.Field>
                                    <Composer.Placeholder>Describe the task in detail…</Composer.Placeholder>
                                    <Composer.Textarea
                                        submitShortcut="cmd-enter"
                                        autoFocus
                                        data-attr="task-composer-input"
                                    />
                                </Composer.Field>
                                <Composer.Footer>
                                    <ComposerModelEffortPickers
                                        selectedModel={newTaskData.model}
                                        selectedEffort={newTaskData.reasoningEffort}
                                        onModelChange={(model) =>
                                            setNewTaskData({
                                                model,
                                                reasoningEffort: resolveEffortForModel(
                                                    newTaskData.reasoningEffort,
                                                    model
                                                ),
                                            })
                                        }
                                        onEffortChange={(reasoningEffort) => setNewTaskData({ reasoningEffort })}
                                    />
                                </Composer.Footer>
                            </Composer.Frame>
                            <Suggestions.Dropdown />
                            <Composer.Submit data-attr="task-composer-send" />
                        </Composer.Root>
                    </div>

                    <Suggestions.Buttons data={DEFAULT_SUGGESTIONS_DATA} />
                </Suggestions.Root>
            </div>
        </div>
    )
}
