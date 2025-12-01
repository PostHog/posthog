import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonMenu, LemonMenuItems, Popover, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { commentsLogic } from 'scenes/comments/commentsLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ActivityScope, SidePanelTab } from '~/types'

import { llmAnalyticsTraceLogic } from '../llmAnalyticsTraceLogic'
import { MAX_TRANSLATE_LENGTH, SUPPORTED_LANGUAGES, messageActionsMenuLogic } from './messageActionsMenuLogic'

export interface MessageActionsMenuProps {
    content: string
}

export const MessageActionsMenu = ({ content }: MessageActionsMenuProps): JSX.Element | null => {
    const { traceId } = useValues(llmAnalyticsTraceLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const commentsLogicProps = {
        scope: ActivityScope.LLM_TRACE,
        item_id: traceId,
    }
    const commentsLogicInstance = commentsLogic(commentsLogicProps)
    const { maybeLoadComments } = useActions(commentsLogicInstance)

    const logic = messageActionsMenuLogic({ content })
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

    if (!content || content.trim().length === 0) {
        return null
    }

    const insertQuoteIntoEditor = (quotedContent: string, retries = 0): void => {
        // Access editor via .values to get the latest value at retry time, not render time
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
        maybeLoadComments()
        openSidePanel(SidePanelTab.Discussion)

        const maxQuoteLength = 500
        const truncatedContent =
            content.length > maxQuoteLength ? content.substring(0, maxQuoteLength) + '...' : content

        const quotedContent = truncatedContent
            .split('\n')
            .map((line) => `> ${line}`)
            .join('\n')

        setTimeout(() => insertQuoteIntoEditor(quotedContent), 100)
    }

    const showDiscussions = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DISCUSSIONS]
    const showTranslation = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TRANSLATION]

    const menuItems: LemonMenuItems = [
        ...(showDiscussions
            ? [
                  {
                      label: 'Start discussion',
                      onClick: handleStartDiscussion,
                      'data-attr': 'llm-analytics-message-start-discussion',
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
                      'data-attr': 'llm-analytics-message-translate',
                  },
              ]
            : []),
    ]

    if (menuItems.length === 0) {
        return null
    }

    const translationText = translation?.translation
    const isTranslatedForCurrentLanguage = translation?.targetLanguage === targetLanguage

    const handleConsentApproved = (): void => {
        setShowConsentPopover(false)
        setShowTranslatePopover(true)
    }

    return (
        <>
            <LemonMenu items={menuItems} placement="bottom-end">
                <LemonButton size="small" noPadding icon={<IconEllipsis />} tooltip="More actions" />
            </LemonMenu>

            {/* AI consent popover - shown first if user hasn't consented */}
            <AIConsentPopoverWrapper
                showArrow
                onApprove={handleConsentApproved}
                onDismiss={() => setShowConsentPopover(false)}
                hidden={!showConsentPopover}
            >
                <div />
            </AIConsentPopoverWrapper>

            {/* Translate popover - only shown after consent */}
            <Popover
                visible={showTranslatePopover}
                onClickOutside={() => setShowTranslatePopover(false)}
                placement="bottom"
                overlay={
                    <div className="p-3 min-w-72 max-w-120">
                        <div className="flex items-center justify-between mb-2">
                            <span className="font-semibold text-sm">Translate message</span>
                            <LemonButton size="xsmall" onClick={() => setShowTranslatePopover(false)} noPadding>
                                <span className="text-lg leading-none">&times;</span>
                            </LemonButton>
                        </div>
                        <div className="border-t pt-3">
                            {isTooLong ? (
                                <div className="text-xs text-warning mb-2">
                                    Message truncated to {MAX_TRANSLATE_LENGTH.toLocaleString()} characters for
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
                                    {translationText && isTranslatedForCurrentLanguage ? 'Re-translate' : 'Translate'}
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
                <div />
            </Popover>
        </>
    )
}
