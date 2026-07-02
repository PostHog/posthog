import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { pulseBriefsGenerateCreate, pulseBriefsList, pulseBriefsRetrieve, pulseBriefConfigsList } from './generated/api'
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
    }),
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
    })),
    afterMount(({ actions }) => {
        actions.loadBriefConfigs()
        actions.loadBriefs()
    }),
])
