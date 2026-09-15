import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'
import { SuggestionCard } from 'scenes/max/components/SuggestionCard'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { composerSeedLogic, runnerPanelLogic } from 'products/posthog_ai/frontend/api/logics'
import { SidePanelRunner } from 'products/posthog_ai/frontend/api/runner'

import { newWorkflowAgentLogic } from './newWorkflowAgentLogic'
import { newWorkflowLogic } from './newWorkflowLogic'
import { NewWorkflowModal } from './NewWorkflowModal'
import { NEW_WORKFLOW_SUGGESTIONS } from './workflowAgentContext'

/** The AI-first "New workflow" screen: the side panel's runner rendered full page, with a way back to the editor. */
export function NewWorkflowAgent(): JSX.Element {
    useMountedLogic(newWorkflowAgentLogic)
    const { openEditorFromAiComposer } = useActions(newWorkflowLogic)
    const { activeCreation } = useValues(runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }))
    // A card only fills the composer (no auto-submit) so the prompt can be tweaked before the agent starts.
    const { setSeed } = useActions(composerSeedLogic({ panelId: MAX_SIDE_PANEL_ID }))
    const fillComposer = (prompt: string): void => {
        setSeed({ prompt, autoSubmit: false })
        const textarea = document.querySelector<HTMLTextAreaElement>('[data-attr="task-composer-input"]')
        textarea?.focus()
        textarea?.setSelectionRange(prompt.length, prompt.length)
    }

    return (
        // While drafting, the runner takes its natural height so the cards sit right under the composer;
        // once a run starts it fills the page like the side panel.
        <div
            className={cn('flex flex-col grow min-h-0', !activeCreation && 'justify-center')}
            data-attr="new-workflow-agent"
        >
            <div className={cn('flex flex-col', activeCreation ? 'grow min-h-0' : 'shrink-0')}>
                <SidePanelRunner panelId={MAX_SIDE_PANEL_ID} />
            </div>
            {!activeCreation && (
                <div className="flex flex-col items-center gap-4 shrink-0 pb-6">
                    <div className="grid grid-cols-1 @min-[40rem]/main-content:grid-cols-2 gap-1 w-full max-w-2xl px-4">
                        {NEW_WORKFLOW_SUGGESTIONS.map((suggestion) => (
                            <SuggestionCard
                                key={suggestion.prompt}
                                title={suggestion.title}
                                description={suggestion.description}
                                icon={iconForType('workflows')}
                                onClick={() => fillComposer(suggestion.prompt)}
                                data-attr="new-workflow-agent-suggestion"
                            />
                        ))}
                    </div>
                    <LemonButton
                        type="tertiary"
                        size="small"
                        data-attr="new-workflow-agent-open-editor"
                        onClick={openEditorFromAiComposer}
                    >
                        Build it in the editor instead
                    </LemonButton>
                </div>
            )}
            <NewWorkflowModal />
        </div>
    )
}
