import { MakeLogicType, actions, connect, kea, listeners, path, reducers } from 'kea'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'
import { v5 as uuid } from 'uuid'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { WorkflowTriggerConfig } from './workflowTriggerPrefill'

export const DISTRIBUTION_WAVE = 'workflows-distribution-v1'
export const DISTRIBUTION_FLAG = 'workflows-distribution'
export const DISTRIBUTION_CONTEXT_PARAM = 'distributionContext'
const MEMORY_TTL = 14 * 24 * 60 * 60 * 1000
const MEMORY_LIMIT = 100

export type DistributionPlacement =
    | 'selected-event'
    | 'native-destination'
    | 'release-announcement'
    | 'sdk-wizard'
    | 'instrumentation-skill'
    | 'contextual-mcp'

interface DistributionSourceContext {
    projectUuid: string
    placementId: DistributionPlacement
    sourceActionId: string
    eligible: boolean
}

export type DistributionSource = DistributionSourceContext &
    ({ trigger?: WorkflowTriggerConfig; templateId?: never } | { templateId: string; trigger?: never })

export interface DistributionContext {
    contextKey: string
    projectUuid: string
    placementId: DistributionPlacement
    arm: 'offer' | 'control'
    eligibleAt: number
    opened?: boolean
    outcome?: 'dismissed' | 'created'
}

export interface DistributionOffer extends DistributionContext {
    trigger?: WorkflowTriggerConfig
    templateId?: string
}

function isAuthorized(projectUuid: string): boolean {
    return (
        teamLogic.values.currentTeam?.uuid === projectUuid &&
        !getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor)
    )
}

function captureStage(context: DistributionContext, stage: string, workflowId?: string, templateId?: string): void {
    try {
        posthog.capture(
            stage === 'draft created' && templateId
                ? 'hog_flow_created_from_template'
                : `workflow distribution ${stage}`,
            {
                project_uuid: context.projectUuid,
                wave_id: DISTRIBUTION_WAVE,
                placement_id: context.placementId,
                context_key: context.contextKey,
                arm: context.arm,
                stage,
                eligible_at: new Date(context.eligibleAt).toISOString(),
                ...(workflowId ? { workflow_id: workflowId } : {}),
                ...(templateId ? { template_id: templateId } : {}),
            }
        )
    } catch {
        return
    }
}

export interface workflowDistributionLogicValues {
    memory: DistributionContext[]
    offers: Record<string, DistributionOffer>
    editorContext: DistributionContext | null
}

export interface workflowDistributionLogicActions {
    offer: (source: DistributionSource) => { source: DistributionSource }
    remember: (context: DistributionContext) => { context: DistributionContext }
    setOffer: (offer: DistributionOffer) => { offer: DistributionOffer }
    removeOffer: (contextKey: string) => { contextKey: string }
    offerShown: (contextKey: string) => { contextKey: string }
    open: (contextKey: string) => { contextKey: string }
    dismiss: (contextKey: string) => { contextKey: string }
    editorArrived: (contextKey?: string) => { contextKey?: string }
    setEditorContext: (context: DistributionContext | null) => { context: DistributionContext | null }
    createStarted: (contextKey?: string) => { contextKey?: string }
    draftCreated: (
        context: DistributionContext,
        workflowId: string,
        templateId?: string
    ) => {
        context: DistributionContext
        workflowId: string
        templateId?: string
    }
    clearTransient: () => {}
}

export type workflowDistributionLogicType = MakeLogicType<
    workflowDistributionLogicValues,
    workflowDistributionLogicActions
>

export const workflowDistributionLogic = kea<workflowDistributionLogicType>([
    path(['products', 'workflows', 'workflowDistributionLogic']),
    connect({ values: [teamLogic, []] }),
    actions({
        offer: (source: DistributionSource) => ({ source }),
        remember: (context: DistributionContext) => ({ context }),
        setOffer: (offer: DistributionOffer) => ({ offer }),
        removeOffer: (contextKey: string) => ({ contextKey }),
        offerShown: (contextKey: string) => ({ contextKey }),
        open: (contextKey: string) => ({ contextKey }),
        dismiss: (contextKey: string) => ({ contextKey }),
        editorArrived: (contextKey?: string) => ({ contextKey }),
        setEditorContext: (context: DistributionContext | null) => ({ context }),
        createStarted: (contextKey?: string) => ({ contextKey }),
        draftCreated: (context: DistributionContext, workflowId: string, templateId?: string) => ({
            context,
            workflowId,
            templateId,
        }),
        clearTransient: () => ({}),
    }),
    reducers({
        memory: [
            [] as DistributionContext[],
            { persist: true },
            {
                remember: (state, { context }) =>
                    [...state.filter((item) => item.contextKey !== context.contextKey), context]
                        .filter((item) => item.eligibleAt > Date.now() - MEMORY_TTL)
                        .slice(-MEMORY_LIMIT),
            },
        ],
        offers: [
            {} as Record<string, DistributionOffer>,
            {
                setOffer: (state, { offer }) => ({ ...state, [offer.contextKey]: offer }),
                removeOffer: (state, { contextKey }) =>
                    Object.fromEntries(Object.entries(state).filter(([key]) => key !== contextKey)),
                clearTransient: () => ({}),
            },
        ],
        editorContext: [
            null as DistributionContext | null,
            {
                setEditorContext: (_, { context }) => context,
                createStarted: () => null,
                clearTransient: () => null,
            },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        offer: ({ source }) => {
            if (
                !source.eligible ||
                !isAuthorized(source.projectUuid) ||
                !source.sourceActionId ||
                source.sourceActionId.length > 128
            ) {
                return
            }
            if (posthog.getGroups().project !== source.projectUuid) {
                return
            }
            const placementFlag = `${DISTRIBUTION_FLAG}-${source.placementId}`
            const overrides = posthog.get_property('$override_feature_flags')
            if (overrides && (DISTRIBUTION_FLAG in overrides || placementFlag in overrides)) {
                return
            }
            const placement = posthog.getFeatureFlagResult(placementFlag, { send_event: false })
            const assignment = posthog.getFeatureFlagResult(DISTRIBUTION_FLAG, { send_event: false })
            if (
                !placement?.enabled ||
                !assignment?.enabled ||
                !['offer', 'control'].includes(assignment.variant ?? '')
            ) {
                return
            }
            const contextKey = uuid(
                JSON.stringify([source.projectUuid, DISTRIBUTION_WAVE, source.placementId, source.sourceActionId]),
                uuid.URL
            )
            const existing = values.memory.find(
                (item) => item.contextKey === contextKey && item.eligibleAt > Date.now() - MEMORY_TTL
            )
            const context: DistributionContext = existing ?? {
                contextKey,
                projectUuid: source.projectUuid,
                placementId: source.placementId,
                arm: assignment.variant as 'offer' | 'control',
                eligibleAt: Date.now(),
            }
            if (!existing) {
                actions.remember(context)
                captureStage(context, 'eligible')
            }
            if (context.arm === 'offer' && !context.outcome) {
                actions.setOffer({ ...context, trigger: source.trigger, templateId: source.templateId })
            }
        },
        offerShown: ({ contextKey }) => {
            const offer = values.offers[contextKey]
            const shown = (cache.shown ??= new Set<string>()) as Set<string>
            if (offer && isAuthorized(offer.projectUuid) && !shown.has(contextKey)) {
                shown.add(contextKey)
                captureStage(offer, 'offer shown')
            }
        },
        open: ({ contextKey }) => {
            const offer = values.offers[contextKey]
            if (!offer || !isAuthorized(offer.projectUuid)) {
                return
            }
            actions.remember({
                contextKey,
                projectUuid: offer.projectUuid,
                placementId: offer.placementId,
                arm: offer.arm,
                eligibleAt: offer.eligibleAt,
                opened: true,
            })
            actions.removeOffer(contextKey)
            captureStage(offer, 'clicked')
            router.actions.push(
                combineUrl(urls.workflowNew(), {
                    mode: 'editor',
                    [DISTRIBUTION_CONTEXT_PARAM]: contextKey,
                    ...(offer.templateId ? { templateId: offer.templateId } : {}),
                    ...(offer.trigger && !offer.templateId ? { trigger: JSON.stringify(offer.trigger) } : {}),
                }).url
            )
        },
        dismiss: ({ contextKey }) => {
            const offer = values.offers[contextKey]
            if (offer && isAuthorized(offer.projectUuid)) {
                const { trigger: _trigger, templateId: _templateId, ...context } = offer
                actions.remember({ ...context, opened: false, outcome: 'dismissed' })
                actions.removeOffer(contextKey)
                captureStage(context, 'dismissed')
            }
        },
        editorArrived: ({ contextKey }) => {
            const context = values.memory.find(
                (item) =>
                    item.contextKey === contextKey &&
                    item.opened &&
                    !item.outcome &&
                    item.eligibleAt > Date.now() - MEMORY_TTL
            )
            actions.setEditorContext(context && isAuthorized(context.projectUuid) ? context : null)
            if (values.editorContext) {
                captureStage(values.editorContext, 'editor arrived')
            }
        },
        createStarted: ({ contextKey }) => {
            const opened = values.memory.find((item) => item.contextKey === contextKey)
            if (opened) {
                actions.remember({ ...opened, opened: false })
            }
        },
        draftCreated: ({ context, workflowId, templateId }) => {
            if (workflowId && isAuthorized(context.projectUuid)) {
                actions.remember({ ...context, opened: false, outcome: 'created' })
                actions.removeOffer(context.contextKey)
                captureStage(context, 'draft created', workflowId, templateId)
            }
        },
        [teamLogic.actionTypes.loadCurrentTeamSuccess]: ({ currentTeam }) => {
            if (
                (values.editorContext && values.editorContext.projectUuid !== currentTeam?.uuid) ||
                Object.values(values.offers).some((offer) => offer.projectUuid !== currentTeam?.uuid)
            ) {
                actions.clearTransient()
            }
        },
    })),
])
