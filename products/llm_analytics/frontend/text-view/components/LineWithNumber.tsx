import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonMenu, LemonMenuItems, Popover, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { commentsLogic } from 'scenes/comments/commentsLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ActivityScope, SidePanelTab } from '~/types'

import {
    MAX_TRANSLATE_LENGTH,
    SUPPORTED_LANGUAGES,
    messageActionsMenuLogic,
} from '../../ConversationDisplay/messageActionsMenuLogic'

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
    const { featureFlags } = useValues(featureFlagLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    const showDiscussions = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DISCUSSIONS] && !!traceId
    const showTranslation = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TRANSLATION]

    const commentsLogicProps = {
        scope: ActivityScope.LLM_TRACE,
        item_id: traceId || '',
    }
    const commentsLogicInstance = commentsLogic(commentsLogicProps)
    const { maybeLoadComments } = useActions(commentsLogicInstance)

    const lineText = `L${padding > 0 ? lineNumber.toString().padStart(padding, '0') : lineNumber}:${content}`
    const logic = messageActionsMenuLogic({ content: lineText })
    const {
        showTranslatePopover,
        showConsentPopover,
        targetLanguage,
        translation,
        translationLoading,
        translationError,
        isTooLong,
        currentLanguageLabel,
        dataProcessingAccepted,
    } = useValues(logic)
    const { setShowTranslatePopover, setShowConsentPopover, setTargetLanguage, translate } = useActions(logic)

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
            'data-attr': 'llm-analytics-line-copy-link',
        },
        ...(showDiscussions
            ? [
                  {
                      label: 'Start discussion',
                      onClick: handleStartDiscussion,
                      'data-attr': 'llm-analytics-line-start-discussion',
                  },
              ]
            : []),
        ...(showTranslation
            ? [
                  {
                      label: 'Translate',
                      onClick: () => {
                          if (dataProcessingAccepted) {
                              setShowTranslatePopover(true)
                          } else {
                              setShowConsentPopover(true)
                          }
                      },
                      'data-attr': 'llm-analytics-line-translate',
                  },
              ]
            : []),
    ]

    const translationText = translation?.translation
    const isTranslatedForCurrentLanguage = translation?.targetLanguage === targetLanguage

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
            {showTranslatePopover && (
                <Popover
                    visible
                    onClickOutside={() => setShowTranslatePopover(false)}
                    placement="bottom"
                    overlay={
                        <div className="p-3 min-w-72 max-w-120">
                            <div className="flex items-center justify-between mb-2">
                                <span className="font-semibold text-sm">Translate line</span>
                                <LemonButton size="xsmall" onClick={() => setShowTranslatePopover(false)} noPadding>
                                    <span className="text-lg leading-none">&times;</span>
                                </LemonButton>
                            </div>
                            <div className="border-t pt-3">
                                {isTooLong ? (
                                    <div className="text-xs text-warning mb-2">
                                        Text truncated to {MAX_TRANSLATE_LENGTH.toLocaleString()} characters for
                                        translation
                                    </div>
                                ) : null}
                                <div className="flex items-center gap-2 mb-3">
                                    <span className="text-sm text-muted">To:</span>
                                    <LemonSelect
                                        size="small"
                                        value={targetLanguage}
                                        onChange={(value) => value && setTargetLanguage(value)}
                                        options={SUPPORTED_LANGUAGES.map((lang) => ({
                                            value: lang.value,
                                            label: lang.label,
                                        }))}
                                    />
                                    <LemonButton
                                        size="small"
                                        type="primary"
                                        onClick={translate}
                                        loading={translationLoading}
                                    >
                                        {translationText && isTranslatedForCurrentLanguage
                                            ? 'Re-translate'
                                            : 'Translate'}
                                    </LemonButton>
                                </div>
                                {translationLoading ? (
                                    <div className="flex items-center justify-center py-4 gap-2">
                                        <Spinner className="text-lg" />
                                        <span className="text-muted">Translating to {currentLanguageLabel}...</span>
                                    </div>
                                ) : translationError ? (
                                    <div className="text-center py-2">
                                        <p className="text-danger mb-2">Translation failed. Please try again.</p>
                                    </div>
                                ) : translationText ? (
                                    <div className="whitespace-pre-wrap text-sm bg-bg-light rounded p-2 max-h-80 overflow-y-auto">
                                        {translationText}
                                    </div>
                                ) : (
                                    <div className="text-center py-4 text-muted text-sm">
                                        Select a language and click Translate
                                    </div>
                                )}
                            </div>
                        </div>
                    }
                >
                    <span />
                </Popover>
            )}
        </span>
    )
}
