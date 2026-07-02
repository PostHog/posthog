import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import {
    pulseBriefsGenerateCreate,
    pulseBriefsList,
    pulseBriefsRetrieve,
    pulseBriefConfigsCreate,
    pulseBriefConfigsDestroy,
    pulseBriefConfigsList,
    pulseBriefConfigsPartialUpdate,
} from './generated/api'
import type {
    BriefConfigApi,
    ProductBriefApi,
    ProductBriefApiSectionsItem,
    ProductBriefListApi,
} from './generated/api.schemas'
import { ProductBriefStatusEnumApi } from './generated/api.schemas'
import type { pulseLogicType } from './pulseLogicType'

/** Narrowed shape of one generated brief section — the API ships sections as untyped dicts. */
export interface BriefSection {
    kind: string
    title: string
    markdown: string
    citations: string[]
    confidence: number
}

function parseSection(section: ProductBriefApiSectionsItem): BriefSection {
    return {
        kind: typeof section.kind === 'string' ? section.kind : '',
        title: typeof section.title === 'string' ? section.title : '',
        markdown: typeof section.markdown === 'string' ? section.markdown : '',
        citations: Array.isArray(section.citations)
            ? section.citations.filter((citation): citation is string => typeof citation === 'string')
            : [],
        confidence: typeof section.confidence === 'number' ? section.confidence : 0,
    }
}

export const BRIEF_POLL_INTERVAL_MS = 3000

/** Key used for briefs generated without a config (the zero-config default brief). */
export const DEFAULT_CONFIG_KEY = 'default'

function isAiConsentError(error: unknown): boolean {
    // The generate endpoint 400s with this DRF validation message when the organization
    // has not approved AI data processing — there is no dedicated error code for it.
    return (
        error instanceof ApiError &&
        error.status === 400 &&
        (error.detail ?? JSON.stringify(error.data ?? '')).includes('AI data processing')
    )
}

function isGeneratingBrief(brief: ProductBriefListApi): boolean {
    return brief.status === ProductBriefStatusEnumApi.Generating
}

export interface BriefConfigForm {
    name: string
    focus_prompt: string
    dashboards: number[]
}

const EMPTY_CONFIG_FORM: BriefConfigForm = { name: '', focus_prompt: '', dashboards: [] }

export const pulseLogic = kea<pulseLogicType>([
    path(['products', 'pulse', 'frontend', 'pulseLogic']),
    actions({
        selectConfig: (configId: string | null) => ({ configId }),
        selectBrief: (briefId: string | null) => ({ briefId }),
        setAiConsentRequired: (aiConsentRequired: boolean) => ({ aiConsentRequired }),
        startPolling: true,
        stopPolling: true,
        pollGeneratingBriefs: true,
        briefsRefreshed: (briefs: ProductBriefApi[]) => ({ briefs }),
        openConfigModal: (config: BriefConfigApi | null) => ({ config }),
        closeConfigModal: true,
        configSaved: (config: BriefConfigApi, created: boolean) => ({ config, created }),
        deleteConfig: (configId: string) => ({ configId }),
        configDeleted: (configId: string) => ({ configId }),
        configDeleteFailed: true,
    }),
    forms(({ actions, values }) => ({
        configForm: {
            defaults: EMPTY_CONFIG_FORM,
            errors: ({ name }: BriefConfigForm) => ({
                name: name.trim() ? undefined : 'Please enter a name',
            }),
            submit: async (formValues: BriefConfigForm) => {
                const teamId = String(getCurrentTeamId())
                const editing = values.editingConfig
                // Only the dashboards anchor is editable here — spread the existing anchors so
                // insight anchors set through the API survive a save from this form.
                const anchors = { ...editing?.anchors, dashboards: formValues.dashboards }
                const payload = { name: formValues.name.trim(), focus_prompt: formValues.focus_prompt, anchors }
                const saved = editing
                    ? await pulseBriefConfigsPartialUpdate(teamId, editing.id, payload)
                    : await pulseBriefConfigsCreate(teamId, payload)
                actions.configSaved(saved, !editing)
            },
        },
    })),
    loaders(({ actions }) => ({
        briefConfigs: [
            [] as BriefConfigApi[],
            {
                loadBriefConfigs: async (): Promise<BriefConfigApi[]> => {
                    const response = await pulseBriefConfigsList(String(getCurrentTeamId()))
                    return response.results
                },
            },
        ],
        briefs: [
            [] as ProductBriefListApi[],
            {
                loadBriefs: async (): Promise<ProductBriefListApi[]> => {
                    const response = await pulseBriefsList(String(getCurrentTeamId()))
                    return response.results
                },
            },
        ],
        generatedBrief: [
            null as ProductBriefApi | null,
            {
                generateBrief: async ({ configId }: { configId: string | null }): Promise<ProductBriefApi | null> => {
                    try {
                        return await pulseBriefsGenerateCreate(String(getCurrentTeamId()), { config_id: configId })
                    } catch (error) {
                        if (isAiConsentError(error)) {
                            // Handled with an in-scene banner — swallow so the global error toast stays quiet.
                            actions.setAiConsentRequired(true)
                            return null
                        }
                        throw error
                    }
                },
            },
        ],
        briefDetail: [
            null as ProductBriefApi | null,
            {
                loadBriefDetail: async ({ briefId }: { briefId: string }): Promise<ProductBriefApi> => {
                    return await pulseBriefsRetrieve(String(getCurrentTeamId()), briefId)
                },
            },
        ],
    })),
    reducers({
        selectedConfigId: [
            null as string | null,
            {
                selectConfig: (_, { configId }) => configId,
            },
        ],
        selectedBriefId: [
            null as string | null,
            {
                selectBrief: (_, { briefId }) => briefId,
            },
        ],
        aiConsentRequired: [
            false,
            {
                setAiConsentRequired: (_, { aiConsentRequired }) => aiConsentRequired,
                generateBrief: () => false,
            },
        ],
        configModalOpen: [
            false,
            {
                openConfigModal: () => true,
                closeConfigModal: () => false,
                configSaved: () => false,
            },
        ],
        editingConfig: [
            null as BriefConfigApi | null,
            {
                openConfigModal: (_, { config }) => config,
            },
        ],
        configIdBeingDeleted: [
            null as string | null,
            {
                deleteConfig: (_, { configId }) => configId,
                configDeleted: () => null,
                configDeleteFailed: () => null,
            },
        ],
        briefConfigs: {
            configSaved: (state, { config, created }) =>
                created ? [config, ...state] : state.map((existing) => (existing.id === config.id ? config : existing)),
            configDeleted: (state, { configId }) => state.filter((config) => config.id !== configId),
        },
        briefs: {
            generateBriefSuccess: (state, { generatedBrief }) => (generatedBrief ? [generatedBrief, ...state] : state),
            briefsRefreshed: (state, { briefs }) => {
                const byId = new Map(briefs.map((brief) => [brief.id, brief]))
                return state.map((brief) => byId.get(brief.id) ?? brief)
            },
        },
        briefDetail: {
            generateBriefSuccess: (state, { generatedBrief }) => generatedBrief ?? state,
            briefsRefreshed: (state, { briefs }) => briefs.find((brief) => brief.id === state?.id) ?? state,
        },
    }),
    selectors({
        visibleBriefs: [
            (s) => [s.briefs, s.selectedConfigId],
            (briefs, selectedConfigId): ProductBriefListApi[] =>
                briefs.filter((brief) => brief.config === selectedConfigId),
        ],
        latestBriefByConfig: [
            (s) => [s.briefs],
            (briefs): Record<string, ProductBriefListApi> => {
                // Briefs come back newest first, so the first one seen per config is the latest.
                const latest: Record<string, ProductBriefListApi> = {}
                for (const brief of briefs) {
                    const key = brief.config ?? DEFAULT_CONFIG_KEY
                    if (!(key in latest)) {
                        latest[key] = brief
                    }
                }
                return latest
            },
        ],
        isGenerating: [
            (s) => [s.briefs, s.generatedBriefLoading],
            (briefs, generatedBriefLoading): boolean => generatedBriefLoading || briefs.some(isGeneratingBrief),
        ],
        briefDetailSections: [
            (s) => [s.briefDetail],
            (briefDetail): BriefSection[] => (briefDetail?.sections ?? []).map(parseSection),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadBriefsSuccess: ({ briefs }) => {
            if (values.selectedBriefId === null && values.visibleBriefs.length > 0) {
                actions.selectBrief(values.visibleBriefs[0].id)
            }
            if (briefs.some(isGeneratingBrief)) {
                actions.startPolling()
            }
        },
        selectConfig: () => {
            actions.selectBrief(values.visibleBriefs.length > 0 ? values.visibleBriefs[0].id : null)
        },
        selectBrief: ({ briefId }) => {
            if (briefId === null) {
                return
            }
            if (values.briefDetail?.id !== briefId) {
                actions.loadBriefDetail({ briefId })
            }
        },
        generateBriefSuccess: ({ generatedBrief }) => {
            if (!generatedBrief) {
                return
            }
            actions.selectBrief(generatedBrief.id)
            actions.startPolling()
        },
        generateBriefFailure: ({ errorObject }) => {
            if (errorObject instanceof ApiError && errorObject.status === 409) {
                lemonToast.info('A brief is already being generated')
            }
        },
        startPolling: () => {
            cache.disposables.add(() => {
                const intervalId = setInterval(() => actions.pollGeneratingBriefs(), BRIEF_POLL_INTERVAL_MS)
                return () => clearInterval(intervalId)
            }, 'briefPoll')
        },
        stopPolling: () => {
            cache.disposables.dispose('briefPoll')
        },
        pollGeneratingBriefs: async (_, breakpoint) => {
            const generating = values.briefs.filter(isGeneratingBrief)
            if (generating.length === 0) {
                actions.stopPolling()
                return
            }
            const updated = await Promise.all(
                generating.map((brief) => pulseBriefsRetrieve(String(getCurrentTeamId()), brief.id))
            )
            breakpoint()
            actions.briefsRefreshed(updated)
        },
        briefsRefreshed: () => {
            if (!values.briefs.some(isGeneratingBrief)) {
                actions.stopPolling()
            }
        },
        openConfigModal: ({ config }) => {
            actions.resetConfigForm({
                name: config?.name ?? '',
                focus_prompt: config?.focus_prompt ?? '',
                dashboards: config?.anchors?.dashboards ?? [],
            })
        },
        configSaved: ({ config, created }) => {
            lemonToast.success(created ? 'Brief config created' : 'Brief config updated')
            if (created) {
                actions.selectConfig(config.id)
            }
        },
        submitConfigFormFailure: ({ error }) => {
            // Field-level validation failures already render inline — only toast API errors.
            if (error instanceof ApiError) {
                lemonToast.error(error.detail || 'Saving the brief config failed')
            }
        },
        deleteConfig: async ({ configId }) => {
            try {
                await pulseBriefConfigsDestroy(String(getCurrentTeamId()), configId)
            } catch {
                actions.configDeleteFailed()
                lemonToast.error('Deleting the brief config failed')
                return
            }
            if (values.selectedConfigId === configId) {
                actions.selectConfig(null)
            }
            actions.configDeleted(configId)
            lemonToast.success('Brief config deleted')
        },
    })),
    afterMount(({ actions }) => {
        actions.loadBriefConfigs()
        actions.loadBriefs()
    }),
])
