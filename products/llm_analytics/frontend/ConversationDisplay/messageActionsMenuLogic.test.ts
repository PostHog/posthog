import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'

import api from '~/lib/api'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    LanguageCode,
    MAX_TRANSLATE_LENGTH,
    SUPPORTED_LANGUAGES,
    messageActionsMenuLogic,
} from './messageActionsMenuLogic'

jest.mock('~/lib/api')

const mockApi = api as jest.Mocked<typeof api>

describe('messageActionsMenuLogic', () => {
    const mockContent = 'Hello, this is a test message'
    const mockTranslationResponse = {
        translation: 'Hola, este es un mensaje de prueba',
        detected_language: 'en',
        provider: 'openai',
    }

    beforeEach(() => {
        jest.clearAllMocks()
        window.localStorage.clear()

        useMocks({
            get: {
                '/api/organizations/@current/': {
                    id: 'test-org',
                    is_ai_data_processing_approved: true,
                },
            },
        })

        mockApi.llmAnalytics = {
            translate: jest.fn().mockResolvedValue(mockTranslationResponse),
        } as any

        initKeaTests()
    })

    describe('reducers', () => {
        describe('showTranslatePopover', () => {
            it('initializes as false', () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                expect(logic.values.showTranslatePopover).toBe(false)
            })

            it('sets to true when setShowTranslatePopover is called with true', async () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions.setShowTranslatePopover(true)
                }).toMatchValues({
                    showTranslatePopover: true,
                })
            })

            it('sets to false when setShowTranslatePopover is called with false', async () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                logic.actions.setShowTranslatePopover(true)

                await expectLogic(logic, () => {
                    logic.actions.setShowTranslatePopover(false)
                }).toMatchValues({
                    showTranslatePopover: false,
                })
            })
        })

        describe('showConsentPopover', () => {
            it('initializes as false', () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                expect(logic.values.showConsentPopover).toBe(false)
            })

            it('toggles consent popover visibility', async () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions.setShowConsentPopover(true)
                }).toMatchValues({
                    showConsentPopover: true,
                })

                await expectLogic(logic, () => {
                    logic.actions.setShowConsentPopover(false)
                }).toMatchValues({
                    showConsentPopover: false,
                })
            })
        })

        describe('targetLanguage', () => {
            it('initializes with default language from localStorage or en', () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                expect(logic.values.targetLanguage).toBe('en')
            })

            it('persists language preference to localStorage', async () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions.setTargetLanguage('es')
                }).toMatchValues({
                    targetLanguage: 'es',
                })

                expect(localStorage.getItem('posthog-translate-language')).toBe('es')
            })

            it('falls back to en for invalid stored language', () => {
                localStorage.setItem('posthog-translate-language', 'invalid')

                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                expect(logic.values.targetLanguage).toBe('en')
            })
        })

        describe('translationError', () => {
            it('clears error on resetTranslation', async () => {
                // Ensure org is loaded first
                const orgLogic = organizationLogic()
                orgLogic.mount()
                await expectLogic(orgLogic).toFinishAllListeners()

                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                // Manually set an error state
                mockApi.llmAnalytics.translate = jest.fn().mockRejectedValueOnce(new Error('API error'))

                await expectLogic(logic, () => {
                    logic.actions.translate()
                }).toFinishAllListeners()

                expect(logic.values.translationError).not.toBeNull()

                await expectLogic(logic, () => {
                    logic.actions.resetTranslation()
                }).toMatchValues({
                    translationError: null,
                })
            })

            it('sets error on translateFailure', async () => {
                // Ensure org is loaded first
                const orgLogic = organizationLogic()
                orgLogic.mount()
                await expectLogic(orgLogic).toFinishAllListeners()

                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                mockApi.llmAnalytics.translate = jest.fn().mockRejectedValue(new Error('Translation failed'))

                await expectLogic(logic, () => {
                    logic.actions.translate()
                }).toFinishAllListeners()

                expect(logic.values.translationError).toBeTruthy()
            })
        })
    })

    describe('selectors', () => {
        describe('isTooLong', () => {
            it('returns false for content under limit', () => {
                const logic = messageActionsMenuLogic({ content: 'short content' })
                logic.mount()

                expect(logic.values.isTooLong).toBe(false)
            })

            it('returns true for content over limit', () => {
                const longContent = 'a'.repeat(MAX_TRANSLATE_LENGTH + 1)
                const logic = messageActionsMenuLogic({ content: longContent })
                logic.mount()

                expect(logic.values.isTooLong).toBe(true)
            })

            it('returns false for content exactly at limit', () => {
                const exactContent = 'a'.repeat(MAX_TRANSLATE_LENGTH)
                const logic = messageActionsMenuLogic({ content: exactContent })
                logic.mount()

                expect(logic.values.isTooLong).toBe(false)
            })
        })

        describe('textToTranslate', () => {
            it('returns full content when under limit', () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                expect(logic.values.textToTranslate).toBe(mockContent)
            })

            it('truncates content when over limit', () => {
                const longContent = 'a'.repeat(MAX_TRANSLATE_LENGTH + 100)
                const logic = messageActionsMenuLogic({ content: longContent })
                logic.mount()

                expect(logic.values.textToTranslate).toHaveLength(MAX_TRANSLATE_LENGTH)
                expect(logic.values.textToTranslate).toBe('a'.repeat(MAX_TRANSLATE_LENGTH))
            })
        })

        describe('currentLanguageLabel', () => {
            it.each(SUPPORTED_LANGUAGES)('returns correct label for %s', async (lang) => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions.setTargetLanguage(lang.value)
                }).toMatchValues({
                    currentLanguageLabel: lang.label,
                })
            })

            it('returns English for default language code', () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                expect(logic.values.currentLanguageLabel).toBe('English')
            })
        })

        describe('dataProcessingAccepted', () => {
            it('returns true when organization has approved AI data processing', async () => {
                useMocks({
                    get: {
                        '/api/organizations/@current/': {
                            id: 'test-org',
                            is_ai_data_processing_approved: true,
                        },
                    },
                })

                const orgLogic = organizationLogic()
                orgLogic.mount()
                await expectLogic(orgLogic).toFinishAllListeners()

                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                expect(logic.values.dataProcessingAccepted).toBe(true)
            })

            it('returns false when organization has not approved AI data processing', async () => {
                useMocks({
                    get: {
                        '/api/organizations/@current/': {
                            id: 'test-org',
                            is_ai_data_processing_approved: false,
                        },
                    },
                })

                initKeaTests()
                const orgLogic = organizationLogic()
                orgLogic.mount()
                await expectLogic(orgLogic).toFinishAllListeners()

                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                expect(logic.values.dataProcessingAccepted).toBe(false)
            })
        })
    })

    describe('loaders', () => {
        describe('translate', () => {
            it('calls API with correct parameters', async () => {
                // Ensure org is loaded first with AI consent approved
                const orgLogic = organizationLogic()
                orgLogic.mount()
                await expectLogic(orgLogic).toFinishAllListeners()

                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                logic.actions.setTargetLanguage('es')

                await expectLogic(logic, () => {
                    logic.actions.translate()
                }).toFinishAllListeners()

                expect(mockApi.llmAnalytics.translate).toHaveBeenCalledWith({
                    text: mockContent,
                    targetLanguage: 'es',
                })
            })

            it('stores translation result with target language', async () => {
                // Ensure org is loaded first with AI consent approved
                const orgLogic = organizationLogic()
                orgLogic.mount()
                await expectLogic(orgLogic).toFinishAllListeners()

                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                logic.actions.setTargetLanguage('es')

                await expectLogic(logic, () => {
                    logic.actions.translate()
                }).toFinishAllListeners()

                expect(logic.values.translation).toEqual({
                    translation: mockTranslationResponse.translation,
                    targetLanguage: 'es',
                })
            })

            it('truncates long content before sending to API', async () => {
                // Ensure org is loaded first with AI consent approved
                const orgLogic = organizationLogic()
                orgLogic.mount()
                await expectLogic(orgLogic).toFinishAllListeners()

                const longContent = 'a'.repeat(MAX_TRANSLATE_LENGTH + 500)
                const logic = messageActionsMenuLogic({ content: longContent })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions.translate()
                }).toFinishAllListeners()

                expect(mockApi.llmAnalytics.translate).toHaveBeenCalledWith({
                    text: 'a'.repeat(MAX_TRANSLATE_LENGTH),
                    targetLanguage: 'en',
                })
            })

            it('throws error when data processing not accepted', async () => {
                useMocks({
                    get: {
                        '/api/organizations/@current/': {
                            id: 'test-org',
                            is_ai_data_processing_approved: false,
                        },
                    },
                })

                initKeaTests()
                const orgLogic = organizationLogic()
                orgLogic.mount()
                await expectLogic(orgLogic).toFinishAllListeners()

                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions.translate()
                }).toFinishAllListeners()

                expect(logic.values.translationError).toBeTruthy()
                expect(mockApi.llmAnalytics.translate).not.toHaveBeenCalled()
            })
        })
    })

    describe('listeners', () => {
        describe('setTargetLanguage', () => {
            it('resets translatedWithLanguage when language changes after translation', async () => {
                // Ensure org is loaded first with AI consent approved
                const orgLogic = organizationLogic()
                orgLogic.mount()
                await expectLogic(orgLogic).toFinishAllListeners()

                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                // First, do a translation
                logic.actions.setTargetLanguage('es')
                await expectLogic(logic, () => {
                    logic.actions.translate()
                }).toFinishAllListeners()

                expect(logic.values.translatedWithLanguage).toBe('es')

                // Change language - translatedWithLanguage should reset via setTargetLanguage reducer
                await expectLogic(logic, () => {
                    logic.actions.setTargetLanguage('fr')
                }).toMatchValues({
                    translatedWithLanguage: null,
                })
            })
        })

        describe('setShowTranslatePopover', () => {
            it('syncs language from localStorage when popover opens', async () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                // Set a language first
                logic.actions.setTargetLanguage('es')
                expect(logic.values.targetLanguage).toBe('es')

                // Set a different language in localStorage
                localStorage.setItem('posthog-translate-language', 'de')

                // Open popover - should sync from localStorage
                await expectLogic(logic, () => {
                    logic.actions.setShowTranslatePopover(true)
                }).toFinishAllListeners()

                expect(logic.values.targetLanguage).toBe('de')
            })

            it('does not change language when popover closes', async () => {
                const logic = messageActionsMenuLogic({ content: mockContent })
                logic.mount()

                logic.actions.setTargetLanguage('fr')
                logic.actions.setShowTranslatePopover(true)

                await expectLogic(logic, () => {
                    logic.actions.setShowTranslatePopover(false)
                }).toFinishAllListeners()

                expect(logic.values.targetLanguage).toBe('fr')
            })
        })
    })

    describe('keying', () => {
        it('creates separate logic instances for different content', () => {
            const logic1 = messageActionsMenuLogic({ content: 'content one' })
            const logic2 = messageActionsMenuLogic({ content: 'content two' })

            logic1.mount()
            logic2.mount()

            logic1.actions.setTargetLanguage('es')
            logic2.actions.setTargetLanguage('fr')

            expect(logic1.values.targetLanguage).toBe('es')
            expect(logic2.values.targetLanguage).toBe('fr')
        })

        it('reuses logic instance for same content', () => {
            const content = 'same content'
            const logic1 = messageActionsMenuLogic({ content })
            const logic2 = messageActionsMenuLogic({ content })

            logic1.mount()
            logic1.actions.setTargetLanguage('ja')

            logic2.mount()

            expect(logic2.values.targetLanguage).toBe('ja')
        })
    })

    describe('supported languages', () => {
        it('has all expected languages', () => {
            const expectedLanguages: LanguageCode[] = [
                'en',
                'es',
                'fr',
                'de',
                'pt',
                'zh',
                'ja',
                'ko',
                'it',
                'nl',
                'ru',
                'ar',
            ]

            const actualLanguages = SUPPORTED_LANGUAGES.map((l) => l.value)

            expect(actualLanguages).toEqual(expectedLanguages)
        })

        it('has labels for all languages', () => {
            for (const lang of SUPPORTED_LANGUAGES) {
                expect(lang.label).toBeTruthy()
                expect(typeof lang.label).toBe('string')
            }
        })
    })
})
