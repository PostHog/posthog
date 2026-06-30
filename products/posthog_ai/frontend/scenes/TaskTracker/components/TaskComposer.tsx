import { useActions, useValues } from 'kea'

import { Composer } from 'products/posthog_ai/frontend/api/primitives'
import { resolveEffortForModel } from 'products/posthog_ai/frontend/utils/composerModels'

import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { ComposerModelEffortPickers } from './ComposerModelEffortPickers'
import { RepositorySelector } from './RepositorySelector'

export function TaskComposer(): JSX.Element {
    const { submitTaskCreateForm, setTaskCreateFormValues } = useActions(taskTrackerSceneLogic)
    const { taskCreateForm, isTaskCreateFormSubmitting } = useValues(taskTrackerSceneLogic)

    return (
        <div className="flex flex-col h-full min-h-0 items-center justify-center overflow-y-auto p-4">
            <div className="w-full max-w-2xl flex flex-col gap-4">
                <h2 className="text-lg font-semibold text-center mb-0">What should the agent do?</h2>

                <RepositorySelector
                    value={taskCreateForm.repositoryConfig}
                    onChange={(config) => setTaskCreateFormValues({ repositoryConfig: config })}
                />

                <Composer.Root
                    value={taskCreateForm.description}
                    onChange={(value) => setTaskCreateFormValues({ description: value })}
                    onSubmit={submitTaskCreateForm}
                    loading={isTaskCreateFormSubmitting}
                >
                    <Composer.Frame>
                        <Composer.Field>
                            <Composer.Placeholder>Describe the task in detail…</Composer.Placeholder>
                            <Composer.Textarea submitShortcut="cmd-enter" autoFocus data-attr="task-composer-input" />
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
                    <Composer.Submit data-attr="task-composer-send" />
                </Composer.Root>
            </div>
        </div>
    )
}
