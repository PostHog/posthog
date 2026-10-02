import posthog from 'posthog-js'

import { toast } from '@posthog/quill'

import { readableErrorMessage } from 'lib/api-error'
import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import {
    hogFlowsCreate,
    hogFlowsDestroy,
    hogFlowsList,
    hogFlowsPartialUpdate,
    hogFlowsRetrieve,
    hogFlowsRunCreate,
    hogFlowsSchedulesCreate,
    hogFlowsSchedulesDestroy,
    hogFlowsSchedulesPartialUpdate,
} from 'products/workflows/frontend/generated/api'
import type { HogFlowApi } from 'products/workflows/frontend/generated/api.schemas'

import {
    loopsCreate,
    loopsDestroy,
    loopsList,
    loopsPartialUpdate,
    loopsRetrieve,
    loopsRunCreate,
    loopsRunsRetrieve,
    loopsSkillBundlesUpdate,
    sandboxList,
    tasksList,
    tasksRunsCancelCreate,
} from '../../generated/api'
import type { SandboxEnvironmentDTOApi } from '../../generated/api.schemas'
import { type LoopFormValues, formValuesToLoopWrite, loopToFormValues } from './form/loopFormValues'
import { hogFlowScheduleMatches } from './form/loopSchedule'
import {
    type LoopHogFlowDetail,
    type LoopHogFlowWrite,
    formValuesToHogFlowWrite,
    hogFlowToFormValues,
    isLoopShapedHogFlow,
} from './form/loopWorkflowMapping'
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

export interface SpaceLoopList {
    loops: SpaceLoop[]
    /** Why the project cannot add a loop, or null when it can. Workflows cap runs instead of loops. */
    limitReason: string | null
}

export async function listSpaceLoops(
    { projectId, workflowBacked }: SpaceLoopsBackend,
    spaceId: string
): Promise<SpaceLoopList> {
    if (workflowBacked) {
        const { results } = await readAllPages((offset) =>
            hogFlowsList(projectId, { origin_product: 'loops', limit: LOOPS_PAGE_SIZE, offset })
        )
        return { loops: spaceLoopsFromHogFlows(results, spaceId), limitReason: null }
    }
    const { results, firstPage } = await readAllPages((offset) =>
        loopsList(projectId, { limit: LOOPS_PAGE_SIZE, offset })
    )
    const max = firstPage?.max_loops_per_team
    const used = firstPage?.total_loop_count
    return {
        loops: spaceLoopsFromLoops(results, spaceId),
        limitReason:
            max !== undefined && used !== undefined && used >= max
                ? `This project reached its limit of ${max} loops. Delete one to add another.`
                : null,
    }
}

async function readAllPages<Page extends { results: unknown[]; next?: string | null }>(
    fetchPage: (offset: number) => Promise<Page>
): Promise<{ results: Page['results'][number][]; firstPage: Page | null }> {
    const results: Page['results'][number][] = []
    let firstPage: Page | null = null
    for (let pageIndex = 0; pageIndex < LOOPS_MAX_PAGES; pageIndex++) {
        const page = await fetchPage(results.length)
        firstPage ??= page
        results.push(...page.results)
        if (!page.next || !page.results.length) {
            break
        }
    }
    return { results, firstPage }
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

export async function stopSpaceLoopRun(projectId: string, taskId: string, runId: string): Promise<void> {
    await tasksRunsCancelCreate(projectId, taskId, runId)
}

export async function listSandboxEnvironments(projectId: string): Promise<SandboxEnvironmentDTOApi[]> {
    const page = await sandboxList(projectId, { limit: 100 })
    return page.results
}

/** A loop opened in the form. `hogFlow` is the workflow the save is based on, for a loop stored as one. */
export interface SpaceLoopFormSource {
    loopId: string
    values: LoopFormValues
    hogFlow: LoopHogFlowDetail | null
    /** Changed in the workflow editor, so a save from the form would drop that work. */
    foreign: boolean
    hadSkill: boolean
}

export async function loadSpaceLoopFormSource(
    { projectId, workflowBacked }: SpaceLoopsBackend,
    loopId: string
): Promise<SpaceLoopFormSource> {
    if (workflowBacked) {
        const hogFlow = await hogFlowsRetrieve(projectId, loopId)
        const foreign = !isLoopShapedHogFlow(hogFlow)
        return { loopId, values: hogFlowToFormValues(hogFlow), hogFlow, foreign, hadSkill: false }
    }
    const loop = await loopsRetrieve(projectId, loopId)
    return {
        loopId,
        values: loopToFormValues(loop),
        hogFlow: null,
        foreign: false,
        hadSkill: !!loop.skill_bundles?.length,
    }
}

/** The graph saved, but the schedule row did not follow, so the loop keeps its old cadence until a new save. */
export class LoopScheduleSaveError extends Error {
    constructor(
        override readonly cause: unknown,
        readonly savedUpdatedAt: string
    ) {
        super('The loop saved, but its schedule did not update.')
        this.name = 'LoopScheduleSaveError'
    }
}

type HogFlowCreateBody = Parameters<typeof hogFlowsCreate>[1]
type HogFlowPatchBody = NonNullable<Parameters<typeof hogFlowsPartialUpdate>[2]>

/**
 * Creates the workflow, then its schedule. A rejected schedule deletes the workflow again, so a failed save
 * leaves nothing behind. Until the schedule exists the workflow never fires.
 */
async function createLoopHogFlow(projectId: string, write: LoopHogFlowWrite): Promise<HogFlowApi> {
    const flow = await hogFlowsCreate(projectId, write.flow as unknown as HogFlowCreateBody)
    if (!write.schedule) {
        return flow
    }
    try {
        await hogFlowsSchedulesCreate(projectId, flow.id, write.schedule)
    } catch (error) {
        // A failed rollback leaves a workflow that never fires, which someone can delete from the list.
        await hogFlowsDestroy(projectId, flow.id).catch(() => undefined)
        throw error
    }
    return flow
}

/**
 * Writes the graph, then makes the schedule row match. A matching row stays as it is, because rewriting it can
 * skip a run that was about to fire. A switch to a GitHub trigger removes the old schedule.
 */
async function updateLoopHogFlow(
    projectId: string,
    existing: LoopHogFlowDetail,
    write: LoopHogFlowWrite
): Promise<void> {
    // The workflow status belongs to the pause switch, and the origin and exit condition stay as they are.
    const { status: _status, origin_product: _origin, exit_condition: _exit, ...content } = write.flow
    const flow = await hogFlowsPartialUpdate(projectId, existing.id, {
        ...content,
        base_updated_at: existing.updated_at,
    } as unknown as HogFlowPatchBody)
    try {
        const current = existing.schedules?.[0]
        if (!write.schedule) {
            for (const schedule of existing.schedules ?? []) {
                await hogFlowsSchedulesDestroy(projectId, existing.id, schedule.id)
            }
        } else if (!current) {
            await hogFlowsSchedulesCreate(projectId, existing.id, write.schedule)
        } else if (!hogFlowScheduleMatches(current, write.schedule)) {
            await hogFlowsSchedulesPartialUpdate(projectId, existing.id, current.id, write.schedule)
        }
    } catch (error) {
        throw new LoopScheduleSaveError(error, flow.updated_at)
    }
}

/** Creates or updates a loop from the form, and returns the loop's id. */
export async function saveSpaceLoop(
    { projectId, workflowBacked }: SpaceLoopsBackend,
    values: LoopFormValues,
    source: SpaceLoopFormSource | null
): Promise<string> {
    if (workflowBacked) {
        if (source?.hogFlow) {
            await updateLoopHogFlow(
                projectId,
                source.hogFlow,
                formValuesToHogFlowWrite(values, { enabled: true, existing: source.hogFlow })
            )
            return source.loopId
        }
        const flow = await createLoopHogFlow(projectId, formValuesToHogFlowWrite(values, { enabled: true }))
        return flow.id
    }
    const body = formValuesToLoopWrite(values)
    const saved = source ? await loopsPartialUpdate(projectId, source.loopId, body) : await loopsCreate(projectId, body)
    if (source?.hadSkill && !values.skill) {
        await loopsSkillBundlesUpdate(projectId, saved.id, { bundles: [] })
    }
    return saved.id
}
