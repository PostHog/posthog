import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { organizationLogic } from 'scenes/organizationLogic'

import {
    pulseBriefsGenerateCreate,
    pulseBriefsList,
    pulseBriefsRetrieve,
    pulseBriefConfigsCreate,
    pulseBriefConfigsDestroy,
    pulseBriefConfigsList,
    pulseBriefConfigsPartialUpdate,
} from './generated/api'
import type { BriefConfigApi, BriefSectionApi, ProductBriefApi, ProductBriefListApi } from './generated/api.schemas'
import { ProductBriefStatusEnumApi } from './generated/api.schemas'
import type { pulseLogicType } from './pulseLogicType'

export const BRIEF_POLL_INTERVAL_MS = 3000

/** Mark a single brief as failed after this many consecutive rounds where its retrieve failed. */
export const MAX_CONSECUTIVE_POLL_FAILURES = 5

/** First page only — deliberate for alpha; load-more is a follow-up (surfaced in the UI, not hidden here). */
const LIST_PAGE_SIZE = 100

export const BRIEF_ALREADY_GENERATING_MESSAGE = 'A brief is already being generated'

/** Shown against a brief we stopped being able to reach while it was generating. */
export const BRIEF_UNREACHABLE_MESSAGE = 'We lost contact while generating this brief. Reload the page to check on it.'

// `code` is a cross-boundary contract with the generate endpoint in products/pulse/backend/api/brief.py.
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
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], organizationLogic, ['currentOrganization']],
    })),
    actions({
        selectConfig: (configId: string | null) => ({ configId }),
        selectBrief: (briefId: string | null) => ({ briefId }),
        setAiConsentRequired: (aiConsentRequired: boolean) => ({ aiConsentRequired }),
        setBriefsHasMore: (hasMore: boolean) => ({ hasMore }),
        startPolling: true,
        stopPolling: true,
        pollGeneratingBriefs: true,
        briefsRefreshed: (briefs: ProductBriefApi[]) => ({ briefs }),
        markBriefFailed: (briefId: string) => ({ briefId }),
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
                    actions.setBriefsHasMore(response.next != null)
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
        briefsHasMore: [
            false,
            {
                setBriefsHasMore: (_, { hasMore }) => hasMore,
            },
        ],
        briefsLoadFailed: [
            false,
            {
                loadBriefs: () => false,
                loadBriefsSuccess: () => false,
                loadBriefsFailure: () => true,
            },
        ],
        briefDetailLoadFailed: [
            false,
            {
                loadBriefDetail: () => false,
                loadBriefDetailSuccess: () => false,
                loadBriefDetailFailure: () => true,
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
            markBriefFailed: (state, { briefId }) =>
                state.map((brief) =>
                    brief.id === briefId && isGeneratingBrief(brief)
                        ? { ...brief, status: ProductBriefStatusEnumApi.Failed, error: BRIEF_UNREACHABLE_MESSAGE }
                        : brief
                ),
        },
        briefDetail: {
            generateBriefSuccess: (state, { generatedBrief }) => generatedBrief ?? state,
            briefsRefreshed: (state, { briefs }) => {
                const updated = briefs.find((brief) => brief.id === state?.id)
                return updated && updated.status !== state?.status ? updated : state
            },
            markBriefFailed: (state, { briefId }) =>
                state?.id === briefId && state.status === ProductBriefStatusEnumApi.Generating
                    ? { ...state, status: ProductBriefStatusEnumApi.Failed, error: BRIEF_UNREACHABLE_MESSAGE }
                    : state,
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
        // Reuse the org-wide AI data-processing gate other AI features check, so the button is
        // blocked up front instead of only reacting to the backend's ai_consent_required error.
        dataProcessingAccepted: [
            (s) => [s.currentOrganization],
            (currentOrganization): boolean => !!currentOrganization?.is_ai_data_processing_approved,
        ],
        briefDetailSections: [
            (s) => [s.briefDetail],
            (briefDetail): readonly BriefSectionApi[] => briefDetail?.sections ?? [],
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadBriefsSuccess: ({ briefs }) => {
            // Auto-select only when nothing is selected yet — on mount, and after a config switch
            // clears the selection. A brief chosen by the user is deliberately left in place.
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
            // Preserve counts across restarts: a second generation (different config) re-fires
            // startPolling while another brief is still polling — a fresh Map would wipe its
            // accumulated failures and restart the give-up ceiling from zero.
            cache.pollFailuresByBrief ??= new Map<string, number>()
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
                // Per-brief failure counting: one brief we can't reach must fail on its own, even while
                // its siblings keep succeeding — a shared counter would reset and never trip.
                const failures: Map<string, number> = cache.pollFailuresByBrief
                const refreshed: ProductBriefApi[] = []
                results.forEach((result, index) => {
                    const briefId = generating[index].id
                    if (result.status === 'fulfilled') {
                        failures.delete(briefId)
                        refreshed.push(result.value)
                        return
                    }
                    const rounds = (failures.get(briefId) ?? 0) + 1
                    failures.set(briefId, rounds)
                    if (rounds >= MAX_CONSECUTIVE_POLL_FAILURES) {
                        failures.delete(briefId)
                        posthog.capture('pulse brief poll gave up', { brief_id: briefId })
                        actions.markBriefFailed(briefId)
                    }
                })
                if (refreshed.length > 0) {
                    actions.briefsRefreshed(refreshed)
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
            posthog.capture(created ? 'pulse config created' : 'pulse config updated', {
                config_id: config.id,
                name: config.name,
            })
            lemonToast.success(created ? 'Brief config created' : 'Brief config updated')
            if (created) {
                actions.selectConfig(config.id)
            }
        },
        submitConfigFormFailure: ({ error }) => {
            // Field-level validation failures already render inline — only toast API errors.
            if (error instanceof ApiError) {
                posthog.captureException(error)
                lemonToast.error(error.detail || 'Saving the brief config failed')
            }
        },
        deleteConfig: async ({ configId }) => {
            try {
                await pulseBriefConfigsDestroy(currentProjectId(), configId)
            } catch (error) {
                posthog.captureException(error)
                actions.configDeleteFailed()
                lemonToast.error('Deleting the brief config failed')
                return
            }
            if (values.selectedConfigId === configId) {
                actions.selectConfig(null)
            }
            actions.configDeleted(configId)
            posthog.capture('pulse config deleted', { config_id: configId })
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
