import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

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
    const { composerShown } = useActions(newWorkflowAgentLogic)
    const { openEditorFromAiComposer } = useActions(newWorkflowLogic)
    useEffect(() => composerShown(), [composerShown])
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
        <div className="flex flex-col grow min-h-0" data-attr="new-workflow-agent">
            {/* Same shape as the tree view's trial banner: the escape hatch rides the banner's action, and it
                stays up during a run so a turn that never creates the draft still leaves a way out. */}
            <LemonBanner
                type="ai"
                className="m-2 shrink-0"
                action={{
                    children: 'Use the editor instead',
                    onClick: openEditorFromAiComposer,
                    'data-attr': 'new-workflow-agent-open-editor',
                }}
            >
                We're trialling building workflows with PostHog AI. Describe what you want and it drafts the workflow
                for you to refine.
            </LemonBanner>
            <div className={cn('flex flex-col', activeCreation ? 'grow min-h-0' : 'shrink-0 mt-auto')}>
                <SidePanelRunner panelId={MAX_SIDE_PANEL_ID} />
            </div>
            {!activeCreation && (
                <div className="flex flex-col items-center gap-4 shrink-0 pb-6 mb-auto">
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
                </div>
            )}
            <NewWorkflowModal />
        </div>
    )
}
