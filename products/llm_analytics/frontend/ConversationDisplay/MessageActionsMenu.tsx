import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { commentsLogic } from 'scenes/comments/commentsLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ActivityScope, SidePanelTab } from '~/types'

import { llmAnalyticsTraceLogic } from '../llmAnalyticsTraceLogic'
import { TranslatePopover } from './TranslatePopover'
import { messageActionsMenuLogic } from './messageActionsMenuLogic'

const MAX_EDITOR_RETRIES = 10
const EDITOR_RETRY_DELAY_MS = 100
const MAX_QUOTE_LENGTH = 500

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
    const { showConsentPopover, dataProcessingAccepted } = useValues(logic)
    const { setShowTranslatePopover, setShowConsentPopover } = useActions(logic)

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
        } else if (retries < MAX_EDITOR_RETRIES) {
            setTimeout(() => insertQuoteIntoEditor(quotedContent, retries + 1), EDITOR_RETRY_DELAY_MS)
        }
    }

    const handleStartDiscussion = (): void => {
        maybeLoadComments()
        openSidePanel(SidePanelTab.Discussion)

        const truncatedContent =
            content.length > MAX_QUOTE_LENGTH ? content.substring(0, MAX_QUOTE_LENGTH) + '...' : content

        const quotedContent = truncatedContent
            .split('\n')
            .map((line) => `> ${line}`)
            .join('\n')

        setTimeout(() => insertQuoteIntoEditor(quotedContent), EDITOR_RETRY_DELAY_MS)
    }

    const isEarlyAdopter = !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
    const showDiscussions = isEarlyAdopter || !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_DISCUSSIONS]
    const showTranslation = isEarlyAdopter || !!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TRANSLATION]

    const menuItems: LemonMenuItems = [
        ...(showDiscussions
            ? [
                  {
                      label: 'Start discussion',
                      onClick: handleStartDiscussion,
                      'data-attr': 'llma-message-start-discussion',
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
                      'data-attr': 'llma-message-translate',
                  },
              ]
            : []),
    ]

    if (menuItems.length === 0) {
        return null
    }

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
            <TranslatePopover content={content} title="Translate message" />
        </>
    )
}
