import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'

import {
    llmAnalyticsScoreDefinitionsCreate,
    llmAnalyticsScoreDefinitionsNewVersionCreate,
    llmAnalyticsScoreDefinitionsPartialUpdate,
} from '../generated/api'
import type { ScoreDefinitionApi } from '../generated/api.schemas'
import { llmAnalyticsScoreDefinitionsLogic } from './llmAnalyticsScoreDefinitionsLogic'
import type { scoreDefinitionModalLogicType } from './scoreDefinitionModalLogicType'
import {
    createDraft,
    buildConfigFromDraft,
    getApiErrorDetail,
    getCurrentProjectId,
    getModalTitle,
    type ScoreDefinitionDraft,
    type ScoreDefinitionModalMode,
    validateDraft,
} from './scoreDefinitionModalUtils'

export interface ScoreDefinitionModalLogicProps {
    mode: ScoreDefinitionModalMode
    scoreDefinition: ScoreDefinitionApi | null
    tabId?: string
}

export const scoreDefinitionModalLogic = kea<scoreDefinitionModalLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'scoreDefinitions', 'scoreDefinitionModalLogic']),
    props({} as ScoreDefinitionModalLogicProps),
    key((props) => `${props.tabId ?? 'default'}-${props.mode}-${props.scoreDefinition?.id ?? 'new'}`),

    actions({
        submit: true,
        beginSubmit: true,
        submitSuccess: true,
        submitFailure: true,
        initializeDraft: (draft: ScoreDefinitionDraft) => ({ draft }),
        setDraftField: (
            field: keyof ScoreDefinitionDraft,
            value: ScoreDefinitionDraft[keyof ScoreDefinitionDraft]
        ) => ({
            field,
            value,
        }),
        updateOptionLabel: (index: number, value: string) => ({ index, value }),
        addOption: true,
        removeOption: (index: number) => ({ index }),
    }),

    reducers({
        draft: [
            ({ mode, scoreDefinition }: ScoreDefinitionModalLogicProps) => createDraft(mode, scoreDefinition),
            {
                initializeDraft: (_, { draft }) => draft,
                setDraftField: (state, { field, value }) => ({
                    ...state,
                    [field]: value,
                }),
                updateOptionLabel: (state, { index, value }) => ({
                    ...state,
                    options: state.options.map((option, optionIndex) =>
                        optionIndex === index ? { ...option, label: value } : option
                    ),
                }),
                addOption: (state) => ({
                    ...state,
                    options: [...state.options, { key: '', label: '' }],
                }),
                removeOption: (state, { index }) => ({
                    ...state,
                    options: state.options.filter((_, optionIndex) => optionIndex !== index),
                }),
            },
        ],
        submitting: [
            false,
            {
                beginSubmit: () => true,
                submitSuccess: () => false,
                submitFailure: () => false,
            },
        ],
    }),

    selectors({
        isCreateMode: [() => [(_, props) => props.mode], (mode): boolean => mode === 'create' || mode === 'duplicate'],
        isMetadataMode: [() => [(_, props) => props.mode], (mode): boolean => mode === 'metadata'],
        isConfigMode: [() => [(_, props) => props.mode], (mode): boolean => mode === 'config'],
        title: [() => [(_, props) => props.mode], (mode): string => getModalTitle(mode)],
    }),

    afterMount(({ actions, props }) => {
        actions.initializeDraft(createDraft(props.mode, props.scoreDefinition))
    }),

    listeners(({ actions, values, props }) => ({
        submit: async () => {
            const draft = values.draft
            const validationError = validateDraft(props.mode, draft)
            if (validationError) {
                lemonToast.error(validationError)
                actions.submitFailure()
                return
            }

            actions.beginSubmit()

            try {
                const config = buildConfigFromDraft(draft)

                if (values.isCreateMode) {
                    await llmAnalyticsScoreDefinitionsCreate(getCurrentProjectId(), {
                        name: draft.name.trim(),
                        description: draft.description.trim(),
                        kind: draft.kind,
                        config,
                    })
                    lemonToast.success(props.mode === 'duplicate' ? 'Scorer duplicated.' : 'Scorer created.')
                } else if (values.isMetadataMode && props.scoreDefinition) {
                    await llmAnalyticsScoreDefinitionsPartialUpdate(getCurrentProjectId(), props.scoreDefinition.id, {
                        name: draft.name.trim(),
                        description: draft.description.trim(),
                    })
                    lemonToast.success('Scorer metadata updated.')
                } else if (values.isConfigMode && props.scoreDefinition) {
                    await llmAnalyticsScoreDefinitionsNewVersionCreate(
                        getCurrentProjectId(),
                        props.scoreDefinition.id,
                        {
                            config,
                        }
                    )
                    lemonToast.success('Scorer version created.')
                } else {
                    lemonToast.error('Failed to save scorer.')
                    actions.submitFailure()
                    return
                }

                actions.submitSuccess()
                const listLogic = llmAnalyticsScoreDefinitionsLogic({ tabId: props.tabId })
                listLogic.actions.loadScoreDefinitions(false)
                listLogic.actions.closeModal()
            } catch (error) {
                lemonToast.error(getApiErrorDetail(error) || 'Failed to save scorer.')
                actions.submitFailure()
            }
        },
    })),
])
