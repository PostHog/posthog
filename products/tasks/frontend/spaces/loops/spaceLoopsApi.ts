import posthog from 'posthog-js'

import { toast } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import {
    hogFlowsDestroy,
    hogFlowsList,
    hogFlowsPartialUpdate,
    hogFlowsRetrieve,
    hogFlowsRunCreate,
} from 'products/workflows/frontend/generated/api'

import {
    loopsDestroy,
    loopsList,
    loopsPartialUpdate,
    loopsRetrieve,
    loopsRunCreate,
    loopsRunsRetrieve,
    tasksList,
} from '../../generated/api'
import {
    SpaceLoop,
    SpaceLoopRun,
    spaceLoopFromHogFlow,
    spaceLoopFromLoop,
    spaceLoopRunFromLoopRun,
    spaceLoopRunFromTask,
    spaceLoopsFromHogFlows,
    spaceLoopsFromLoops,
} from './spaceLoops'

// PostHog Desktop reads the same page size, so both apps show the same loops.
const LOOPS_LIST_LIMIT = 100
export const SPACE_LOOP_RUNS_LIMIT = 10

/**
 * Loop requests for one project. Loops live in the loops API, or as workflows when `loops-hog-flows` is on,
 * so every call takes the backend the project uses.
 */
export interface SpaceLoopsBackend {
    projectId: string
    workflowBacked: boolean
}

export function spaceLoopsBackend(
    featureFlags: FeatureFlagsSet,
    currentTeamId: number | null
): SpaceLoopsBackend | null {
    return currentTeamId
        ? { projectId: String(currentTeamId), workflowBacked: !!featureFlags[FEATURE_FLAGS.LOOPS_HOG_FLOWS] }
        : null
}

export async function listSpaceLoops(
    { projectId, workflowBacked }: SpaceLoopsBackend,
    spaceId: string
): Promise<SpaceLoop[]> {
    if (workflowBacked) {
        const page = await hogFlowsList(projectId, { origin_product: 'loops', limit: LOOPS_LIST_LIMIT })
        return spaceLoopsFromHogFlows(page.results, spaceId)
    }
    const page = await loopsList(projectId, { limit: LOOPS_LIST_LIMIT })
    return spaceLoopsFromLoops(page.results, spaceId)
}

export async function retrieveSpaceLoop(
    { projectId, workflowBacked }: SpaceLoopsBackend,
    loopId: string
): Promise<SpaceLoop> {
    return workflowBacked
        ? spaceLoopFromHogFlow(await hogFlowsRetrieve(projectId, loopId))
        : spaceLoopFromLoop(await loopsRetrieve(projectId, loopId))
}

export async function listSpaceLoopRuns(
    { projectId, workflowBacked }: SpaceLoopsBackend,
    loopId: string
): Promise<SpaceLoopRun[]> {
    if (workflowBacked) {
        // Run history is an audit trail, so archived tasks still count as runs.
        const page = await tasksList(projectId, {
            hog_flow_id: loopId,
            limit: SPACE_LOOP_RUNS_LIMIT,
            ordering: '-created_at',
            archived: 'all',
        })
        return page.results.map(spaceLoopRunFromTask)
    }
    const page = await loopsRunsRetrieve(projectId, loopId, { limit: SPACE_LOOP_RUNS_LIMIT })
    return page.results.map(spaceLoopRunFromLoopRun)
}

/** Pauses or resumes a loop. A paused loop workflow goes back to draft, the same as PostHog Desktop does it. */
export async function setSpaceLoopEnabled(
    { projectId, workflowBacked }: SpaceLoopsBackend,
    loopId: string,
    enabled: boolean
): Promise<void> {
    if (workflowBacked) {
        await hogFlowsPartialUpdate(projectId, loopId, { status: enabled ? 'active' : 'draft' })
        return
    }
    await loopsPartialUpdate(projectId, loopId, { enabled })
}

/** Pauses or resumes a loop from the list or the loop page, and says so when it fails. Returns whether it saved. */
export async function saveSpaceLoopEnabled(
    backend: SpaceLoopsBackend,
    loopId: string,
    enabled: boolean,
    surface: 'list' | 'detail'
): Promise<boolean> {
    try {
        await setSpaceLoopEnabled(backend, loopId, enabled)
        // pinned: analytics event name, renaming breaks dashboards
        posthog.capture('space loop enabled toggled', { enabled, surface })
        return true
    } catch {
        toast.error({ title: enabled ? 'Couldn’t resume this loop' : 'Couldn’t pause this loop' })
        return false
    }
}

/** Starts a run now. Returns why the loops API refused it, or null when a run started. */
export async function runSpaceLoop(
    { projectId, workflowBacked }: SpaceLoopsBackend,
    loopId: string
): Promise<string | null> {
    if (workflowBacked) {
        // One key per click: the server dedupes a retry of the same click, and a second click is a second run.
        await hogFlowsRunCreate(projectId, loopId, {}, { headers: { 'Idempotency-Key': crypto.randomUUID() } })
        return null
    }
    const result = await loopsRunCreate(projectId, loopId)
    return result.created ? null : result.reason
}

export async function deleteSpaceLoop({ projectId, workflowBacked }: SpaceLoopsBackend, loopId: string): Promise<void> {
    if (workflowBacked) {
        await hogFlowsDestroy(projectId, loopId)
        return
    }
    await loopsDestroy(projectId, loopId)
}
