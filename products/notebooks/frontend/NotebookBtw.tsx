import { useMemo } from 'react'

import { LemonModal } from '@posthog/lemon-ui'

import { useComposerOverride, useWelcomeOverride } from 'products/posthog_ai/frontend/api/logics'
import { SidePanelRunner } from 'products/posthog_ai/frontend/api/runner'

import { getNotebookBtwContext } from './notebookBtwContext'
import type { NotebookBtwSession } from './notebookBtwLogic'

const COMPOSER_OVERRIDE = {
    placeholder: 'Ask a side question...',
    subheadline: null,
    hideRepositorySelector: true,
    hideSuggestions: true,
    hideRecentTasks: true,
    hideOnboardingReplay: true,
}

export function NotebookBtw({ session, onClose }: { session: NotebookBtwSession; onClose: () => void }): JSX.Element {
    const contextItems = useMemo(() => getNotebookBtwContext(session.context), [session.context])
    useComposerOverride(COMPOSER_OVERRIDE)
    useWelcomeOverride(['What would you like to know?'])

    return (
        <LemonModal
            isOpen
            title="Btw mode"
            description="Ask a side question. Replies stay in this conversation."
            onClose={onClose}
            width={640}
        >
            <div className="flex h-[65vh] min-h-0 flex-col overflow-hidden">
                <SidePanelRunner panelId={session.panelId} contextItems={contextItems} attachApplyBackInstructions={false} />
            </div>
        </LemonModal>
    )
}
