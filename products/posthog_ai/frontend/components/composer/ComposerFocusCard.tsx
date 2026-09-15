import { useActions } from 'kea'
import { useState } from 'react'

import { IconCollapse, IconExpand, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IconOpenInNew } from 'lib/lemon-ui/icons'

import { Query } from '~/queries/Query/Query'
import { QueryContext } from '~/queries/types'

import { composerFocusLogic } from '../../logics/composerFocusLogic'
import type { RegisteredComposerFocus } from '../../types/composerFocusTypes'

const QUERY_CONTEXT_POSTHOG_AI: QueryContext = { limitContext: 'posthog_ai' } as const

export interface ComposerFocusCardProps {
    focus: RegisteredComposerFocus
    /** The copy above a running thread: preview collapsed and no caption, so the thread keeps the space. */
    compact?: boolean
}

/** The thing the user is asking about, pinned above the composer or above the thread. */
export function ComposerFocusCard({ focus, compact = false }: ComposerFocusCardProps): JSX.Element {
    const { closeFocus } = useActions(composerFocusLogic)
    const [isPreviewShown, setIsPreviewShown] = useState(!compact)
    const hasPreview = !!focus.query || !!focus.code

    return (
        <div
            className="w-full flex flex-col gap-2 rounded border border-primary bg-surface-primary p-2"
            data-attr="composer-focus-card"
        >
            <div className="flex items-center gap-1 min-w-0">
                <span className="flex-1 min-w-0 truncate font-semibold" title={focus.title}>
                    {focus.title}
                </span>
                {compact && hasPreview && (
                    <LemonButton
                        size="xsmall"
                        icon={isPreviewShown ? <IconCollapse /> : <IconExpand />}
                        tooltip={isPreviewShown ? 'Hide preview' : 'Show preview'}
                        onClick={() => setIsPreviewShown(!isPreviewShown)}
                        data-attr="composer-focus-toggle-preview"
                    />
                )}
                {focus.openUrl && (
                    <LemonButton size="xsmall" icon={<IconOpenInNew />} to={focus.openUrl} targetBlank tooltip="Open" />
                )}
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    tooltip="Remove from this conversation"
                    onClick={() => closeFocus(focus.providerId)}
                    data-attr="composer-focus-close"
                />
            </div>
            {isPreviewShown &&
                (focus.query ? (
                    // Capped so the textbox below stays in view in a ~500px side panel.
                    <div className="flex flex-col h-[220px] overflow-auto">
                        <Query query={focus.query} readOnly embedded context={QUERY_CONTEXT_POSTHOG_AI} />
                    </div>
                ) : focus.code ? (
                    <CodeSnippet
                        language={focus.codeLanguage === 'python' ? Language.Python : Language.SQL}
                        compact
                        maxLinesWithoutExpansion={10}
                        thing={focus.codeLanguage === 'python' ? 'Python code' : 'SQL'}
                    >
                        {focus.code}
                    </CodeSnippet>
                ) : null)}
            {!compact && focus.caption && <p className="m-0 text-xs text-secondary">{focus.caption}</p>}
        </div>
    )
}
