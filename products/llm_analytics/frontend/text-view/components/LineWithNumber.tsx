import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { commentsLogic } from 'scenes/comments/commentsLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ActivityScope, SidePanelTab } from '~/types'

import { TranslatePopover } from '../../ConversationDisplay/TranslatePopover'
import { messageActionsMenuLogic } from '../../ConversationDisplay/messageActionsMenuLogic'

interface LineWithNumberProps {
    lineNumber: number
    content: string
    isActive: boolean
    padding: number
    traceId?: string
    onCopyPermalink?: (lineNumber: number) => void
}

export function LineWithNumber({
    lineNumber,
    content,
    isActive,
    padding,
    traceId,
    onCopyPermalink,
}: LineWithNumberProps): JSX.Element {
    const lineRef = useRef<HTMLSpanElement>(null)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    const commentsLogicProps = {
        scope: ActivityScope.LLM_TRACE,
        item_id: traceId || '',
    }
    const commentsLogicInstance = commentsLogic(commentsLogicProps)
    const { maybeLoadComments } = useActions(commentsLogicInstance)

    const lineText = `L${padding > 0 ? lineNumber.toString().padStart(padding, '0') : lineNumber}:${content}`
    const logic = messageActionsMenuLogic({ content: lineText })
    const { showTranslatePopover, showConsentPopover, dataProcessingAccepted } = useValues(logic)
    const { setShowTranslatePopover, setShowConsentPopover } = useActions(logic)

    useEffect(() => {
        if (isActive && lineRef.current) {
            lineRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
            lineRef.current.classList.add('bg-warning-highlight', 'border-l-4', 'border-warning')
            const timer = setTimeout(() => {
                lineRef.current?.classList.remove('bg-warning-highlight', 'border-l-4', 'border-warning')
            }, 3000)
            return () => clearTimeout(timer)
        }
    }, [isActive])

    const handleCopyPermalink = (): void => {
        if (onCopyPermalink) {
            onCopyPermalink(lineNumber)
        }
    }

    const insertQuoteIntoEditor = (quotedContent: string, retries = 0): void => {
        const editor = commentsLogicInstance.values.richContentEditor
        if (editor) {
            editor.clear()
            editor.pasteContent(0, quotedContent + '\n\n')
            editor.focus('end')
        } else if (retries < 10) {
            setTimeout(() => insertQuoteIntoEditor(quotedContent, retries + 1), 100)
        }
    }

    const handleStartDiscussion = (): void => {
        if (!traceId) {
            return
        }
        maybeLoadComments()
        openSidePanel(SidePanelTab.Discussion)

        const quotedContent = `> L${lineNumber}: ${content.trim()}`
        setTimeout(() => insertQuoteIntoEditor(quotedContent), 100)
    }

    const handleConsentApproved = (): void => {
        setShowConsentPopover(false)
        setShowTranslatePopover(true)
    }

    const paddedLineNumber = padding > 0 ? lineNumber.toString().padStart(padding, '0') : lineNumber.toString()

    const menuItems: LemonMenuItems = [
        {
            label: 'Copy link',
            onClick: handleCopyPermalink,
            'data-attr': 'llma-line-copy-link',
        },
        ...(traceId
            ? [
                  {
                      label: 'Start discussion',
                      onClick: handleStartDiscussion,
                      'data-attr': 'llma-line-start-discussion',
                  },
              ]
            : []),
        {
            label: 'Translate',
            onClick: () => {
                if (dataProcessingAccepted) {
                    setShowTranslatePopover(true)
                } else {
                    setShowConsentPopover(true)
                }
            },
            'data-attr': 'llma-line-translate',
        },
    ]

    return (
        <span ref={lineRef}>
            <LemonMenu items={menuItems} placement="bottom-start">
                <button type="button" className="text-muted hover:text-link cursor-pointer">
                    L{paddedLineNumber}:
                </button>
            </LemonMenu>
            {content}
            {showConsentPopover && (
                <AIConsentPopoverWrapper
                    showArrow
                    onApprove={handleConsentApproved}
                    onDismiss={() => setShowConsentPopover(false)}
                    hidden={false}
                >
                    <span />
                </AIConsentPopoverWrapper>
            )}
            {showTranslatePopover && <TranslatePopover content={lineText} title="Translate line" />}
        </span>
    )
}
