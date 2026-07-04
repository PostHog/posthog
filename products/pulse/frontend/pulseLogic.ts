import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

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

/** A `"type:ref"` evidence citation split into its parts, e.g. `insight:abc123`. */
export interface BriefCitation {
    type: string
    ref: string
}

/** Narrowed shape of one generated brief section — the API ships sections as untyped dicts. */
export interface BriefSection {
    kind: string
    title: string
    markdown: string
    citations: BriefCitation[]
    confidence: number
}

function parseCitation(citation: string): BriefCitation {
    const separatorIndex = citation.indexOf(':')
    if (separatorIndex <= 0) {
        return { type: '', ref: citation }
    }
    return { type: citation.slice(0, separatorIndex), ref: citation.slice(separatorIndex + 1) }
}

/** A hallucinated non-numeric ref must fall back to a plain tag, not a dead `/NaN` link. */
function numericSceneUrl(ref: string, buildUrl: (id: number) => string): string | undefined {
    const id = Number(ref)
    return Number.isFinite(id) ? buildUrl(id) : undefined
}

/**
 * Citation types that link out, in one table so the tag label and its URL can't drift.
 * Unknown types render as plain tags. The backend source of truth for the linkable kinds is
 * `CandidateKind` in products/pulse/backend/generation/explain.py. Flags and experiments are
 * cited by numeric id (the scene route param); keys/names live in the candidate labels instead.
 */
export const CITATION_TYPES: Record<string, { label: string; url: (ref: string) => string | undefined }> = {
    insight: { label: 'Insight', url: (ref) => urls.insightView(ref as InsightShortId) },
    dashboard: { label: 'Dashboard', url: (ref) => urls.dashboard(ref) },
    flag: { label: 'Feature flag', url: (ref) => numericSceneUrl(ref, urls.featureFlag) },
    experiment: { label: 'Experiment', url: (ref) => numericSceneUrl(ref, (id) => urls.experiment(id)) },
    annotation: { label: 'Annotation', url: (ref) => numericSceneUrl(ref, urls.annotation) },
}

function parseSection(section: ProductBriefApiSectionsItem): BriefSection {
    return {
        kind: typeof section.kind === 'string' ? section.kind : '',
        title: typeof section.title === 'string' ? section.title : '',
        markdown: typeof section.markdown === 'string' ? section.markdown : '',
        citations: Array.isArray(section.citations)
            ? section.citations
                  .filter((citation): citation is string => typeof citation === 'string')
                  .map(parseCitation)
            : [],
        confidence: typeof section.confidence === 'number' ? section.confidence : 0,
    }
}

export const BRIEF_POLL_INTERVAL_MS = 3000

/** Stop polling and surface an error after this many consecutive rounds where every retrieve failed. */
export const MAX_CONSECUTIVE_POLL_FAILURES = 5

/** First page only — deliberate for alpha; load-more is a follow-up. */
const LIST_PAGE_SIZE = 100

export const BRIEF_ALREADY_GENERATING_MESSAGE = 'A brief is already being generated'

// Cross-boundary contract: must match the ValidationError code raised by the generate endpoint
// in products/pulse/backend/api/brief.py — rename both sides together.
const AI_CONSENT_ERROR_CODE = 'ai_consent_required'

function currentProjectId(): string {
    return String(getCurrentTeamId())
}

function isAiConsentError(error: unknown): boolean {
    return error instanceof ApiError && error.code === AI_CONSENT_ERROR_CODE
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
    connect(() => ({ values: [featureFlagLogic, ['featureFlags']] })),
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
                const editing = values.editingConfig
                // Only the dashboards anchor is editable here — spread the existing anchors so
                // insight anchors set through the API survive a save from this form.
                const anchors = { ...editing?.anchors, dashboards: formValues.dashboards }
                const payload = { name: formValues.name.trim(), focus_prompt: formValues.focus_prompt, anchors }
                const saved = editing
                    ? await pulseBriefConfigsPartialUpdate(currentProjectId(), editing.id, payload)
                    : await pulseBriefConfigsCreate(currentProjectId(), payload)
                actions.configSaved(saved, !editing)
            },
        },
    })),
    loaders(({ actions }) => ({
        briefConfigs: [
            [] as BriefConfigApi[],
            {
                loadBriefConfigs: async (): Promise<BriefConfigApi[]> => {
                    const response = await pulseBriefConfigsList(currentProjectId(), { limit: LIST_PAGE_SIZE })
                    return response.results
                },
            },
        ],
        briefs: [
            [] as ProductBriefListApi[],
            {
                loadBriefs: async (): Promise<ProductBriefListApi[]> => {
                    const response = await pulseBriefsList(currentProjectId(), { limit: LIST_PAGE_SIZE })
                    return response.results
                },
            },
        ],
        generatedBrief: [
            null as ProductBriefApi | null,
            {
                generateBrief: async ({ configId }: { configId: string | null }): Promise<ProductBriefApi | null> => {
                    try {
                        return await pulseBriefsGenerateCreate(currentProjectId(), { config_id: configId })
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
                    return await pulseBriefsRetrieve(currentProjectId(), briefId)
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
                // Only swap in briefs whose status actually changed, so identities stay
                // stable across no-op poll ticks and derived selectors don't churn.
                const byId = new Map(briefs.map((brief) => [brief.id, brief]))
                let changed = false
                const next = state.map((brief) => {
                    const updated = byId.get(brief.id)
                    if (updated && updated.status !== brief.status) {
                        changed = true
                        return updated
                    }
                    return brief
                })
                return changed ? next : state
            },
        },
        briefDetail: {
            generateBriefSuccess: (state, { generatedBrief }) => generatedBrief ?? state,
            briefsRefreshed: (state, { briefs }) => {
                const updated = briefs.find((brief) => brief.id === state?.id)
                return updated && updated.status !== state?.status ? updated : state
            },
        },
    }),
    selectors({
        visibleBriefs: [
            (s) => [s.briefs, s.selectedConfigId],
            (briefs, selectedConfigId): ProductBriefListApi[] =>
                briefs.filter((brief) => brief.config === selectedConfigId),
        ],
        // Scoped to the selected focus: the backend locks generation per team+config, so a brief
        // generating for another config must not disable "Run brief now" for this one.
        isGeneratingForSelectedConfig: [
            (s) => [s.visibleBriefs, s.generatedBriefLoading],
            (visibleBriefs, generatedBriefLoading): boolean =>
                generatedBriefLoading || visibleBriefs.some(isGeneratingBrief),
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
                lemonToast.info(BRIEF_ALREADY_GENERATING_MESSAGE)
            }
        },
        startPolling: () => {
            cache.pollFailureRounds = 0
            cache.disposables.add(() => {
                const intervalId = setInterval(() => actions.pollGeneratingBriefs(), BRIEF_POLL_INTERVAL_MS)
                return () => clearInterval(intervalId)
            }, 'briefPoll')
        },
        stopPolling: () => {
            cache.disposables.dispose('briefPoll')
        },
        pollGeneratingBriefs: async () => {
            // The single stop decision: a tick with nothing left to poll ends the interval.
            const generating = values.briefs.filter(isGeneratingBrief)
            if (generating.length === 0) {
                actions.stopPolling()
                return
            }
            if (cache.pollInFlight) {
                return // A slow previous tick is still fetching — skip instead of stacking requests.
            }
            cache.pollInFlight = true
            try {
                const results = await Promise.allSettled(
                    generating.map((brief) => pulseBriefsRetrieve(currentProjectId(), brief.id))
                )
                const refreshed = results
                    .filter(
                        (result): result is PromiseFulfilledResult<ProductBriefApi> => result.status === 'fulfilled'
                    )
                    .map((result) => result.value)
                if (refreshed.length > 0) {
                    cache.pollFailureRounds = 0
                    actions.briefsRefreshed(refreshed)
                    return
                }
                // Every retrieve failed — count rounds so a persistent outage becomes legible instead
                // of an interval spinning forever behind a "Generating…" state.
                cache.pollFailureRounds = (cache.pollFailureRounds ?? 0) + 1
                if (cache.pollFailureRounds >= MAX_CONSECUTIVE_POLL_FAILURES) {
                    actions.stopPolling()
                    lemonToast.error('Checking brief status keeps failing — reload the page to retry')
                }
            } finally {
                cache.pollInFlight = false
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
                await pulseBriefConfigsDestroy(currentProjectId(), configId)
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
    afterMount(({ actions, values }) => {
        // The scene renders NotFound without the flag — don't fire the pulse API calls either.
        if (!values.featureFlags[FEATURE_FLAGS.PULSE]) {
            return
        }
        actions.loadBriefConfigs()
        actions.loadBriefs()
    }),
])
