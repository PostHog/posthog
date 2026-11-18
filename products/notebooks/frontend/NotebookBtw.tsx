import { useCallback, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { SidePanelRunner } from 'products/posthog_ai/frontend/api/runner'

import { getNotebookBtwContext } from './notebookBtwContext'
import type { NotebookBtwSession } from './notebookBtwLogic'

const CONVERSATION_DESCRIPTION =
    'Sent messages are saved in PostHog AI history, separately from this notebook. After a refresh, reopen the conversation from history.'

const COMPOSER_OVERRIDE = {
    placeholder: 'Ask a side question...',
    subheadline: null,
    hideRepositorySelector: true,
    hideSuggestions: true,
    hideRecentTasks: true,
    hideOnboardingReplay: true,
}

export function NotebookBtw({
    session,
    onClose,
    presentation,
}: {
    session: NotebookBtwSession
    onClose: () => void
    presentation: 'sidebar' | 'modal'
}): JSX.Element {
    const contextItems = useMemo(() => getNotebookBtwContext(session.context), [session.context])

    // Move the portal host so resizing preserves the composer draft and active conversation.
    const [chatContainer] = useState(() => document.createElement('div'))
    const attachChat = useCallback(
        (host: HTMLDivElement | null) => {
            if (host) {
                chatContainer.className = 'flex h-full min-h-0 flex-col'
                host.appendChild(chatContainer)
            }
        },
        [chatContainer]
    )

    return (
        <>
            {presentation === 'modal' ? (
                <LemonModal isOpen title="BTW" description={CONVERSATION_DESCRIPTION} onClose={onClose} width={640}>
                    <div ref={attachChat} className="h-[65vh] min-h-0 overflow-hidden" />
                </LemonModal>
            ) : (
                <aside
                    aria-label="BTW"
                    className="sticky top-4 flex h-[calc(100dvh-9rem)] w-96 shrink-0 flex-col self-start overflow-hidden rounded border bg-surface-primary"
                >
                    <header className="flex items-start justify-between gap-2 border-b p-4">
                        <div>
                            <h3 className="mb-1">BTW</h3>
                            <p className="mb-0 text-secondary">{CONVERSATION_DESCRIPTION}</p>
                        </div>
                        <LemonButton
                            icon={<IconX />}
                            size="small"
                            onClick={onClose}
                            aria-label="Close BTW"
                            data-attr="notebook-btw-close"
                        />
                    </header>
                    <div ref={attachChat} className="min-h-0 flex-1 overflow-hidden p-4" />
                </aside>
            )}
            {createPortal(
                <SidePanelRunner
                    panelId={session.panelId}
                    contextItems={contextItems}
                    composerOverride={COMPOSER_OVERRIDE}
                    welcomeHeadlines={['What would you like to know?']}
                    attachApplyBackInstructions={false}
                />,
                chatContainer
            )}
        </>
    )
}
