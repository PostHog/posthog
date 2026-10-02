import posthog from 'posthog-js'

import { toast } from '@posthog/quill'

import { readableErrorMessage } from 'lib/api-error'
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
} from './spaceLoopMapping'

const LOOPS_PAGE_SIZE = 100
// The list filters by space in the browser, so it reads every page. The cap stops a runaway loop.
const LOOPS_MAX_PAGES = 20
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
        const flows = await readAllPages((offset) =>
            hogFlowsList(projectId, { origin_product: 'loops', limit: LOOPS_PAGE_SIZE, offset })
        )
        return spaceLoopsFromHogFlows(flows, spaceId)
    }
    const loops = await readAllPages((offset) => loopsList(projectId, { limit: LOOPS_PAGE_SIZE, offset }))
    return spaceLoopsFromLoops(loops, spaceId)
}

async function readAllPages<T>(
    fetchPage: (offset: number) => Promise<{ results: T[]; next?: string | null }>
): Promise<T[]> {
    const results: T[] = []
    for (let pageIndex = 0; pageIndex < LOOPS_MAX_PAGES; pageIndex++) {
        const page = await fetchPage(results.length)
        results.push(...page.results)
        if (!page.next || !page.results.length) {
            break
        }
    }
    return results
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
    } catch (error) {
        // Resuming a workflow loop checks its steps again, and the server names the step to fix.
        toast.error({
            title: enabled ? 'Couldn’t resume this loop' : 'Couldn’t pause this loop',
            description: readableErrorMessage(error) ?? 'Try again.',
        })
        return false
    }
}

/**
 * Starts a run now. Returns why the loops API refused it, or null when a run started. A workflow run sends
 * `idempotencyKey`, so a retry with the same key after an unclear failure cannot start a second run.
 */
export async function runSpaceLoop(
    { projectId, workflowBacked }: SpaceLoopsBackend,
    loopId: string,
    idempotencyKey: string
): Promise<string | null> {
    if (workflowBacked) {
        await hogFlowsRunCreate(projectId, loopId, {}, { headers: { 'Idempotency-Key': idempotencyKey } })
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
