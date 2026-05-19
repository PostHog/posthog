import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { addProductIntent } from 'lib/utils/product-intents'
import { SURVEY_CREATED_SOURCE, defaultSurveyAppearance } from 'scenes/surveys/constants'
import { isThumbQuestion } from 'scenes/surveys/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { Survey, SurveyAppearance, SurveyQuestionBranchingType, SurveyQuestionType, SurveyType } from '~/types'

import type { feedbackSurveyWizardLogicType } from './feedbackSurveyWizardLogicType'

export type WizardStep = 'intro' | 'configure' | 'implement'

const BASE_SURVEY_NAME = 'LLM feedback'

function generateUniqueSurveyName(existingNames: Set<string>): string {
    if (!existingNames.has(BASE_SURVEY_NAME.toLowerCase())) {
        return BASE_SURVEY_NAME
    }
    let counter = 2
    while (existingNames.has(`${BASE_SURVEY_NAME} (${counter})`.toLowerCase())) {
        counter++
    }
    return `${BASE_SURVEY_NAME} (${counter})`
}

export const feedbackSurveyWizardLogic = kea<feedbackSurveyWizardLogicType>([
    path(['scenes', 'llm-analytics', 'feedbackSurveyWizardLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        setStep: (step: WizardStep) => ({ step }),
        setSurveyName: (name: string) => ({ name }),
        setFollowUpEnabled: (enabled: boolean) => ({ enabled }),
        setFollowUpQuestion: (question: string) => ({ question }),
        updateAppearance: (updates: Partial<SurveyAppearance>) => ({ updates }),
        selectExistingSurvey: (survey: Survey) => ({ survey }),
        viewSurvey: true,
    }),
    reducers({
        step: [
            'intro' as WizardStep,
            {
                setStep: (_, { step }) => step,
                createSurveySuccess: () => 'implement' as WizardStep,
                selectExistingSurvey: () => 'implement' as WizardStep,
            },
        ],
        selectedSurvey: [
            null as Survey | null,
            {
                selectExistingSurvey: (_, { survey }) => survey,
            },
        ],
        surveyName: [
            BASE_SURVEY_NAME as string,
            {
                setSurveyName: (_, { name }) => name,
            },
        ],
        followUpEnabled: [
            true,
            {
                setFollowUpEnabled: (_, { enabled }) => enabled,
            },
        ],
        followUpQuestion: [
            'What went wrong?',
            {
                setFollowUpQuestion: (_, { question }) => question,
            },
        ],
        appearance: [
            {} as SurveyAppearance,
            {
                updateAppearance: (state, { updates }) => ({ ...state, ...updates }),
            },
        ],
    }),
    loaders({
        allSurveys: [
            [] as Survey[],
            {
                loadAllSurveys: async () => {
                    const response = await api.surveys.list()
                    return response.results
                },
            },
        ],
        createdSurvey: [
            null as Survey | null,
            {
                createSurvey: async () => {
                    const { surveyName, followUpEnabled, followUpQuestion, appearance, surveysNeedEnabling } =
                        feedbackSurveyWizardLogic.values

                    // Enable surveys if not already enabled
                    if (surveysNeedEnabling) {
                        teamLogic.actions.updateCurrentTeam({ surveys_opt_in: true })
                    }

                    const questions: Survey['questions'] = [
                        {
                            type: SurveyQuestionType.Rating,
                            question: 'Was this response helpful?', // not actually displayed, so not user-configurable
                            display: 'emoji',
                            scale: 2,
                            lowerBoundLabel: '', // unused for thumb surveys
                            upperBoundLabel: '', // unused for thumb surveys
                            skipSubmitButton: true,
                            ...(followUpEnabled
                                ? {
                                      branching: {
                                          type: SurveyQuestionBranchingType.ResponseBased,
                                          responseValues: {
                                              positive: SurveyQuestionBranchingType.End,
                                              negative: 1,
                                          },
                                      },
                                  }
                                : {}),
                        },
                    ]

                    if (followUpEnabled) {
                        questions.push({
                            type: SurveyQuestionType.Open,
                            question: followUpQuestion,
                            optional: true,
                        })
                    }

                    const survey = await api.surveys.create({
                        name: surveyName || BASE_SURVEY_NAME,
                        type: SurveyType.API,
                        questions,
                        appearance: followUpEnabled ? appearance : undefined,
                        start_date: dayjs().toISOString(),
                    })

                    eventUsageLogic.actions.reportSurveyCreated(survey, false, 'llm_analytics')
                    addProductIntent({
                        product_type: ProductKey.SURVEYS,
                        intent_context: ProductIntentContext.SURVEY_CREATED,
                        metadata: {
                            survey_id: survey.id,
                            source: SURVEY_CREATED_SOURCE.LLM_ANALYTICS,
                            created_successfully: true,
                        },
                    })

                    return survey
                },
            },
        ],
    }),
    selectors({
        defaultAppearance: [
            (s) => [s.currentTeam],
            (currentTeam): SurveyAppearance => ({
                ...defaultSurveyAppearance,
                ...currentTeam?.survey_config?.appearance,
            }),
        ],
        existingSurveyNames: [
            (s) => [s.allSurveys],
            (allSurveys): Set<string> => new Set(allSurveys.map((survey) => survey.name.toLowerCase())),
        ],
        nameIsDuplicate: [
            (s) => [s.surveyName, s.existingSurveyNames],
            (surveyName, existingSurveyNames): boolean =>
                surveyName.trim() !== '' && existingSurveyNames.has(surveyName.trim().toLowerCase()),
        ],
        canCreateSurvey: [
            (s) => [s.surveyName, s.nameIsDuplicate, s.followUpEnabled, s.followUpQuestion],
            (surveyName, nameIsDuplicate, followUpEnabled, followUpQuestion): boolean =>
                surveyName.trim() !== '' && !nameIsDuplicate && (!followUpEnabled || followUpQuestion.trim() !== ''),
        ],
        disabledReason: [
            (s) => [s.surveyName, s.nameIsDuplicate, s.followUpEnabled, s.followUpQuestion],
            (surveyName, nameIsDuplicate, followUpEnabled, followUpQuestion): string | undefined => {
                if (nameIsDuplicate) {
                    return 'A survey with this name already exists'
                }
                if (!surveyName.trim()) {
                    return 'Survey name is required'
                }
                if (followUpEnabled && !followUpQuestion.trim()) {
                    return 'Follow-up question is required'
                }
                return undefined
            },
        ],
        eligibleSurveys: [
            (s) => [s.allSurveys],
            (allSurveys): Survey[] => {
                return allSurveys
                    .filter((survey) => {
                        const firstQuestion = survey.questions?.[0]
                        return survey.type === SurveyType.API && firstQuestion && isThumbQuestion(firstQuestion)
                    })
                    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
                    .slice(0, 3)
            },
        ],
        activeSurvey: [
            (s) => [s.createdSurvey, s.selectedSurvey],
            (createdSurvey, selectedSurvey): Survey | null => createdSurvey ?? selectedSurvey,
        ],
        surveysNeedEnabling: [(s) => [s.currentTeam], (currentTeam): boolean => !currentTeam?.surveys_opt_in],
    }),
    listeners(({ actions, values }) => ({
        loadAllSurveysSuccess: ({ allSurveys }) => {
            const existingNames = new Set(allSurveys.map((s: Survey) => s.name.toLowerCase()))
            actions.setSurveyName(generateUniqueSurveyName(existingNames))
        },
        createSurveySuccess: () => {
            lemonToast.success('Survey created!')
        },
        createSurveyFailure: () => {
            lemonToast.error('Failed to create survey')
        },
        viewSurvey: () => {
            if (values.activeSurvey?.id) {
                router.actions.push(urls.survey(values.activeSurvey.id))
            }
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadAllSurveys()
        actions.updateAppearance(values.defaultAppearance)
    }),
])
