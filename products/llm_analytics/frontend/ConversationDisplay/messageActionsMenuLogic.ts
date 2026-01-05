import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { organizationLogic } from 'scenes/organizationLogic'

import supportedLanguagesJson from '../../shared/supported_languages.json'
import type { messageActionsMenuLogicType } from './messageActionsMenuLogicType'

const STORAGE_KEY = 'posthog-translate-language'
export const MAX_TRANSLATE_LENGTH = 10000

/** Simple string hash for generating unique keys from content */
const hashString = (str: string): string => {
    let hash = 0
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i)
        hash = (hash << 5) - hash + char
        hash = hash & hash // Convert to 32-bit integer
    }
    return hash.toString(36)
}

export const SUPPORTED_LANGUAGES = supportedLanguagesJson.map((lang) => ({
    value: lang.code,
    label: lang.label,
})) as readonly { value: string; label: string }[]

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]['value']

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

export interface MessageActionsMenuLogicProps {
    content: string
}

export const messageActionsMenuLogic = kea<messageActionsMenuLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'ConversationDisplay', 'messageActionsMenuLogic']),
    props({} as MessageActionsMenuLogicProps),
    key((props) => hashString(props.content)),
    actions({
        setShowTranslatePopover: (show: boolean) => ({ show }),
        setShowConsentPopover: (show: boolean) => ({ show }),
        setTargetLanguage: (language: LanguageCode) => ({ language }),
        resetTranslation: true,
    }),
    reducers({
        showTranslatePopover: [
            false,
            {
                setShowTranslatePopover: (_, { show }) => show,
            },
        ],
        showConsentPopover: [
            false,
            {
                setShowConsentPopover: (_, { show }) => show,
            },
        ],
        targetLanguage: [
            getStoredLanguage() as LanguageCode,
            {
                setTargetLanguage: (_, { language }) => {
                    setStoredLanguage(language)
                    return language
                },
            },
        ],
        translatedWithLanguage: [
            null as LanguageCode | null,
            {
                translateSuccess: (_, { translation }) => (translation.translation ? translation.targetLanguage : null),
                resetTranslation: () => null,
                setTargetLanguage: (state, { language }) => (state !== language ? null : state),
            },
        ],
        translationError: [
            null as string | null,
            {
                translate: () => null,
                translateSuccess: () => null,
                translateFailure: (_, { error }) => error,
                resetTranslation: () => null,
            },
        ],
    }),
    selectors({
        isTooLong: [(s) => [s.content], (content) => content.length > MAX_TRANSLATE_LENGTH],
        textToTranslate: [
            (s) => [s.content, s.isTooLong],
            (content, isTooLong) => (isTooLong ? content.substring(0, MAX_TRANSLATE_LENGTH) : content),
        ],
        content: [() => [(_, props) => props.content], (content) => content],
        currentLanguageLabel: [
            (s) => [s.targetLanguage],
            (targetLanguage) => SUPPORTED_LANGUAGES.find((lang) => lang.value === targetLanguage)?.label || 'English',
        ],
        dataProcessingAccepted: [
            () => [organizationLogic.selectors.currentOrganization],
            (currentOrganization): boolean => !!currentOrganization?.is_ai_data_processing_approved,
        ],
    }),
    loaders(({ values }) => ({
        translation: [
            null as { translation: string; targetLanguage: LanguageCode } | null,
            {
                translate: async () => {
                    if (!values.dataProcessingAccepted) {
                        throw new Error('AI data processing must be approved to translate')
                    }
                    const response = await api.llmAnalytics.translate({
                        text: values.textToTranslate,
                        targetLanguage: values.targetLanguage,
                    })
                    return {
                        translation: response.translation,
                        targetLanguage: values.targetLanguage,
                    }
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setTargetLanguage: ({ language }) => {
            if (values.translatedWithLanguage && values.translatedWithLanguage !== language) {
                actions.resetTranslation()
            }
        },
        setShowTranslatePopover: ({ show }) => {
            if (show) {
                const storedLang = getStoredLanguage()
                if (storedLang !== values.targetLanguage) {
                    actions.setTargetLanguage(storedLang)
                    actions.resetTranslation()
                }
            }
        },
    })),
])
