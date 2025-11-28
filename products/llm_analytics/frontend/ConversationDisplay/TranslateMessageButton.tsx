import { useState } from 'react'

import { Popover, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

const STORAGE_KEY = 'posthog-translate-language'

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

// Simple globe/translate icon since @posthog/icons doesn't have one
const IconTranslate = (): JSX.Element => (
    <svg
        xmlns="http://www.w3.org/2000/svg"
        width="1em"
        height="1em"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
    >
        <path d="m5 8 6 6" />
        <path d="m4 14 6-6 2-3" />
        <path d="M2 5h12" />
        <path d="M7 2h1" />
        <path d="m22 22-5-10-5 10" />
        <path d="M14 18h6" />
    </svg>
)

export interface TranslateMessageButtonProps {
    content: string
}

export const TranslateMessageButton = ({ content }: TranslateMessageButtonProps): JSX.Element | null => {
    const [loading, setLoading] = useState(false)
    const [isOpen, setIsOpen] = useState(false)
    const [translation, setTranslation] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [targetLanguage, setTargetLanguage] = useState<LanguageCode>(getStoredLanguage)
    const [translatedWithLanguage, setTranslatedWithLanguage] = useState<LanguageCode | null>(null)

    // Don't show button for empty content
    if (!content || content.trim().length === 0) {
        return null
    }

    const handleLanguageChange = (value: LanguageCode | null): void => {
        if (value) {
            setTargetLanguage(value)
            setStoredLanguage(value)
            // Clear cached translation if language changed
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
            const response = await api.llmAnalytics.translate({ text: content, targetLanguage })
            setTranslation(response.translation)
            setTranslatedWithLanguage(targetLanguage)
        } catch (e) {
            setError('Translation failed. Please try again.')
            console.error('Translation error:', e)
        } finally {
            setLoading(false)
        }
    }

    const handleClick = (): void => {
        setIsOpen(true)
    }

    const currentLanguageLabel = SUPPORTED_LANGUAGES.find((lang) => lang.value === targetLanguage)?.label || 'English'

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            placement="bottom"
            overlay={
                <div className="p-3 min-w-72 max-w-100">
                    <div className="flex items-center justify-between mb-2">
                        <span className="font-semibold text-sm">Translate message</span>
                        <LemonButton size="xsmall" onClick={() => setIsOpen(false)} noPadding>
                            <span className="text-lg leading-none">&times;</span>
                        </LemonButton>
                    </div>
                    <div className="border-t pt-3">
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
                            <div className="whitespace-pre-wrap text-sm bg-bg-light rounded p-2">{translation}</div>
                        ) : (
                            <div className="text-center py-4 text-muted text-sm">
                                Select a language and click Translate
                            </div>
                        )}
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                noPadding
                icon={<IconTranslate />}
                tooltip="Translate message"
                onClick={handleClick}
            />
        </Popover>
    )
}
