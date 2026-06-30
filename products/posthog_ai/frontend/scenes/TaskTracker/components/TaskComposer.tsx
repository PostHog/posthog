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

import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { ComposerModelEffortPickers } from './ComposerModelEffortPickers'
import { RepositorySelector } from './RepositorySelector'

export function TaskComposer(): JSX.Element {
    const { submitTaskCreateForm, setTaskCreateFormValues, setActiveSuggestionGroup, applySuggestion } =
        useActions(taskTrackerSceneLogic)
    const { taskCreateForm, isTaskCreateFormSubmitting, activeSuggestionGroup, headline, sendDisabledReason } =
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

                <div className="w-full">
                    <RepositorySelector
                        value={taskCreateForm.repositoryConfig}
                        onChange={(config) => setTaskCreateFormValues({ repositoryConfig: config })}
                    />
                </div>

                <Suggestions.Root
                    activeGroup={activeSuggestionGroup}
                    onActiveGroupChange={setActiveSuggestionGroup}
                    onSelectSuggestion={handleSelectSuggestion}
                    onNavigate={(url) => router.actions.push(url)}
                >
                    <Composer.Root
                        value={taskCreateForm.description}
                        onChange={(value) => setTaskCreateFormValues({ description: value })}
                        onSubmit={submitTaskCreateForm}
                        loading={isTaskCreateFormSubmitting}
                        disabledReason={sendDisabledReason}
                        textAreaRef={textAreaRef}
                    >
                        <Composer.Frame>
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
                                    selectedModel={taskCreateForm.model}
                                    selectedEffort={taskCreateForm.reasoningEffort}
                                    onModelChange={(model) =>
                                        setTaskCreateFormValues({
                                            model,
                                            reasoningEffort: resolveEffortForModel(taskCreateForm.reasoningEffort, model),
                                        })
                                    }
                                    onEffortChange={(reasoningEffort) => setTaskCreateFormValues({ reasoningEffort })}
                                />
                            </Composer.Footer>
                        </Composer.Frame>
                        <Suggestions.Dropdown />
                        <Composer.Submit data-attr="task-composer-send" />
                    </Composer.Root>

                    <Suggestions.Buttons data={DEFAULT_SUGGESTIONS_DATA} />
                </Suggestions.Root>
            </div>
        </div>
    )
}
