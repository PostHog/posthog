import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { LemonMenu, LemonMenuItems, Popover, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { commentsLogic } from 'scenes/comments/commentsLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ActivityScope, SidePanelTab } from '~/types'

import { llmAnalyticsTraceLogic } from '../llmAnalyticsTraceLogic'

const STORAGE_KEY = 'posthog-translate-language'
const MAX_TRANSLATE_LENGTH = 10000

const SUPPORTED_LANGUAGES = [
    { value: 'en', label: 'English' },
    { value: 'es', label: 'Spanish' },
    { value: 'fr', label: 'French' },
    { value: 'de', label: 'German' },
    { value: 'pt', label: 'Portuguese' },
    { value: 'zh', label: 'Chinese' },
    { value: 'ja', label: 'Japanese' },
    { value: 'ko', label: 'Korean' },
    { value: 'it', label: 'Italian' },
    { value: 'nl', label: 'Dutch' },
    { value: 'ru', label: 'Russian' },
    { value: 'ar', label: 'Arabic' },
] as const

type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]['value']

const getStoredLanguage = (): LanguageCode => {
    try {
        const stored = localStorage.getItem(STORAGE_KEY)
        if (stored && SUPPORTED_LANGUAGES.some((lang) => lang.value === stored)) {
            return stored as LanguageCode
        }
    } catch {
        // localStorage might not be available
    }
    return 'en'
}

const setStoredLanguage = (language: LanguageCode): void => {
    try {
        localStorage.setItem(STORAGE_KEY, language)
    } catch {
        // localStorage might not be available
    }
}

export interface MessageActionsMenuProps {
    content: string
}

export const MessageActionsMenu = ({ content }: MessageActionsMenuProps): JSX.Element | null => {
    const { traceId } = useValues(llmAnalyticsTraceLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const commentsLogicProps = {
        scope: ActivityScope.LLM_TRACE,
        item_id: traceId,
    }
    const logic = commentsLogic(commentsLogicProps)
    const { maybeLoadComments } = useActions(logic)

    const [showTranslatePopover, setShowTranslatePopover] = useState(false)
    const [loading, setLoading] = useState(false)
    const [translation, setTranslation] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [targetLanguage, setTargetLanguage] = useState<LanguageCode>(getStoredLanguage)
    const [translatedWithLanguage, setTranslatedWithLanguage] = useState<LanguageCode | null>(null)

    const isTooLong = content.length > MAX_TRANSLATE_LENGTH
    const textToTranslate = isTooLong ? content.substring(0, MAX_TRANSLATE_LENGTH) : content

    // Use callback to get fresh editor reference when needed
    const insertQuoteIntoEditor = useCallback(
        (quotedContent: string, retries = 0): void => {
            const editor = logic.values.richContentEditor
            if (editor) {
                editor.clear()
                editor.pasteContent(0, quotedContent + '\n\n')
                editor.focus('end')
            } else if (retries < 10) {
                // Retry up to 10 times (1 second total) waiting for editor to mount
                setTimeout(() => insertQuoteIntoEditor(quotedContent, retries + 1), 100)
            }
        },
        [logic]
    )

    if (!content || content.trim().length === 0) {
        return null
    }

    const handleStartDiscussion = (): void => {
        maybeLoadComments()
        openSidePanel(SidePanelTab.Discussion)

        // Truncate content for the quote if it's too long
        const maxQuoteLength = 500
        const truncatedContent =
            content.length > maxQuoteLength ? content.substring(0, maxQuoteLength) + '...' : content

        // Format as markdown blockquote (prefix each line with >)
        const quotedContent = truncatedContent
            .split('\n')
            .map((line) => `> ${line}`)
            .join('\n')

        // Start trying to insert after a short delay for panel to open
        setTimeout(() => insertQuoteIntoEditor(quotedContent), 100)
    }

    const handleLanguageChange = (value: LanguageCode | null): void => {
        if (value) {
            setTargetLanguage(value)
            setStoredLanguage(value)
            if (translatedWithLanguage && translatedWithLanguage !== value) {
                setTranslation(null)
                setTranslatedWithLanguage(null)
            }
        }
    }

    const handleTranslate = async (): Promise<void> => {
        setError(null)
        setLoading(true)
        try {
            const response = await api.llmAnalytics.translate({ text: textToTranslate, targetLanguage })
            setTranslation(response.translation)
            setTranslatedWithLanguage(targetLanguage)
        } catch (e) {
            setError('Translation failed. Please try again.')
            console.error('Translation error:', e)
        } finally {
            setLoading(false)
        }
    }

    const currentLanguageLabel = SUPPORTED_LANGUAGES.find((lang) => lang.value === targetLanguage)?.label || 'English'

    const menuItems: LemonMenuItems = [
        {
            label: 'Start discussion',
            onClick: handleStartDiscussion,
            'data-attr': 'llm-analytics-message-start-discussion',
        },
        {
            label: 'Translate',
            onClick: () => {
                const storedLang = getStoredLanguage()
                if (storedLang !== targetLanguage) {
                    setTargetLanguage(storedLang)
                    setTranslation(null)
                    setTranslatedWithLanguage(null)
                }
                setShowTranslatePopover(true)
            },
            'data-attr': 'llm-analytics-message-translate',
        },
    ]

    return (
        <>
            <LemonMenu items={menuItems} placement="bottom-end">
                <LemonButton size="small" noPadding icon={<IconEllipsis />} tooltip="More actions" />
            </LemonMenu>

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
                                    onChange={handleLanguageChange}
                                    options={SUPPORTED_LANGUAGES.map((lang) => ({
                                        value: lang.value,
                                        label: lang.label,
                                    }))}
                                />
                                {/* eslint-disable-next-line @typescript-eslint/no-misused-promises */}
                                <LemonButton size="small" type="primary" onClick={handleTranslate} disabled={loading}>
                                    {translation && translatedWithLanguage === targetLanguage
                                        ? 'Re-translate'
                                        : 'Translate'}
                                </LemonButton>
                            </div>
                            {loading ? (
                                <div className="flex items-center justify-center py-4 gap-2">
                                    <Spinner className="text-lg" />
                                    <span className="text-muted">Translating to {currentLanguageLabel}...</span>
                                </div>
                            ) : error ? (
                                <div className="text-center py-2">
                                    <p className="text-danger mb-2">{error}</p>
                                </div>
                            ) : translation ? (
                                <div className="whitespace-pre-wrap text-sm bg-bg-light rounded p-2 max-h-80 overflow-y-auto">
                                    {translation}
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
