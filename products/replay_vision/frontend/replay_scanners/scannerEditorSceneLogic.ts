import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { combineUrl, router, urlToAction } from 'kea-router'
import type { LocationChangedPayload } from 'kea-router/lib/types'

import { GuidedWizardStep } from 'lib/components/GuidedWizard/GuidedWizardStepper'
import { FEATURE_FLAGS } from 'lib/constants'
import { type FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'
import { Breadcrumb } from '~/types'

import { VISION_ROOT_BREADCRUMB, scannerBreadcrumb } from '../utils/breadcrumbs'

export type ScannerEditorStep = 'goal' | 'overview' | 'details' | 'configure' | 'triggers' | 'budget'
// The manual wizard's stepper; overview belongs to the goal-based flow only, so it stays out.
const SCANNER_EDITOR_STEPS: readonly ScannerEditorStep[] = ['goal', 'details', 'configure', 'triggers', 'budget']
// The recordings-first experiment arm asks which recordings to watch before what to look for in them.
const RECORDINGS_FIRST_SCANNER_EDITOR_STEPS: readonly ScannerEditorStep[] = [
    'goal',
    'details',
    'triggers',
    'configure',
    'budget',
]

export function scannerEditorSteps(recordingsFirst: boolean): readonly ScannerEditorStep[] {
    return recordingsFirst ? RECORDINGS_FIRST_SCANNER_EDITOR_STEPS : SCANNER_EDITOR_STEPS
}

/** Position of every step, with the goal flow's overview between the goal and the manual steps. */
export function scannerEditorStepOrder(recordingsFirst: boolean): Record<ScannerEditorStep, number> {
    const [first, ...rest] = scannerEditorSteps(recordingsFirst)
    return Object.fromEntries([first, 'overview', ...rest].map((step, index) => [step, index])) as Record<
        ScannerEditorStep,
        number
    >
}

/** The step after `step` in the stepper, or null on the last step and on the overview, which is outside it. */
export function nextScannerEditorStep(
    step: ScannerEditorStep,
    steps: readonly ScannerEditorStep[]
): ScannerEditorStep | null {
    const index = steps.indexOf(step)
    return index === -1 ? null : (steps[index + 1] ?? null)
}

export const STEP_LABELS: Record<ScannerEditorStep, string> = {
    goal: 'Goal',
    overview: 'Overview',
    details: 'Details',
    configure: 'Configure',
    triggers: 'Recordings',
    budget: 'Budget',
}
const RECORDINGS_FIRST_STEP_LABELS: Record<ScannerEditorStep, string> = {
    ...STEP_LABELS,
    configure: 'Prompt & output',
    triggers: 'Target recordings',
    budget: 'Sampling & limits',
}

export function scannerStepLabels(recordingsFirst: boolean): Record<ScannerEditorStep, string> {
    return recordingsFirst ? RECORDINGS_FIRST_STEP_LABELS : STEP_LABELS
}

export function scannerStepperSteps(recordingsFirst: boolean): GuidedWizardStep<ScannerEditorStep>[] {
    const labels = scannerStepLabels(recordingsFirst)
    return scannerEditorSteps(recordingsFirst).map((step) => ({
        step,
        label: labels[step],
        // pinned: data-attr for autocapture, renaming breaks dashboards, so the goal step keeps its old name
        dataAttr: `vision-editor-step-${step === 'goal' ? 'template' : step}`,
    }))
}

export interface ScannerFieldErrors {
    scanner_config?: unknown
    sampling_rate?: unknown
    credit_limit?: unknown
    duration?: unknown
}

/** Steps that mount no validated field, so leaving them must not run whole-form validation. */
const UNVALIDATED_SCANNER_STEPS: readonly ScannerEditorStep[] = ['goal', 'details']

// Fallback for error shapes that carry no message, so an errored step is never silently clean
function fieldErrorMessages(error: unknown): string[] {
    if (!error) {
        return []
    }
    if (typeof error === 'string') {
        return [error]
    }
    if (typeof error === 'object') {
        const nested = Object.values(error).flatMap((value) => fieldErrorMessages(value))
        if (nested.length > 0) {
            return nested
        }
    }
    return ['This step has errors to fix']
}

/** Which step mounts each validated field. The stepper badges and the post-submit jump both read this. */
export function scannerStepErrors(errors: ScannerFieldErrors): Record<ScannerEditorStep, string[]> {
    return {
        goal: [],
        overview: [],
        details: [],
        configure: fieldErrorMessages(errors.scanner_config),
        triggers: fieldErrorMessages(errors.duration),
        budget: [...fieldErrorMessages(errors.sampling_rate), ...fieldErrorMessages(errors.credit_limit)],
    }
}

/** Earliest step rendering an errored field, so a failed submit lands where the user can fix it. */
export function firstErroredScannerStep(
    errors: ScannerFieldErrors,
    steps: readonly ScannerEditorStep[] = SCANNER_EDITOR_STEPS
): ScannerEditorStep | null {
    const stepErrors = scannerStepErrors(errors)
    return steps.find((step) => stepErrors[step].length > 0) ?? null
}

/**
 * Whether Next can leave `step` without running whole-form validation. In the recordings-first arm the
 * required prompt comes after the recordings step, so only this step's and earlier steps' fields may hold it back.
 */
export function advancesWithoutSubmit(
    step: ScannerEditorStep,
    recordingsFirst: boolean,
    errors: ScannerFieldErrors
): boolean {
    if (!recordingsFirst) {
        return UNVALIDATED_SCANNER_STEPS.includes(step)
    }
    const steps = scannerEditorSteps(true)
    const index = steps.indexOf(step)
    if (index === -1 || index === steps.length - 1) {
        return false
    }
    const stepErrors = scannerStepErrors(errors)
    return steps.slice(0, index + 1).every((s) => stepErrors[s].length === 0)
}

/**
 * Step URL carrying the current query string. Params such as ?from=overview decide where the editor
 * returns, so every hop between steps has to preserve them, backwards as well as forwards.
 */
export function scannerStepUrlWithParams(
    step: ScannerEditorStep,
    scannerId: string,
    searchParams: Record<string, any>
): string {
    return combineUrl(scannerStepUrl(step, scannerId), searchParams).url
}

export const EDITOR_RETURN_TAB_PARAM = 'return_tab'

export function scannerEditUrl(scannerId: string, returnTab: string | null): string {
    return combineUrl(
        urls.replayVisionScannerConfigure(scannerId),
        returnTab ? { [EDITOR_RETURN_TAB_PARAM]: returnTab } : {}
    ).url
}

export function scannerStepUrl(step: ScannerEditorStep, scannerId: string): string {
    switch (step) {
        case 'goal':
            return urls.replayVisionScannerGoal(scannerId)
        case 'overview':
            return urls.replayVisionScannerOverview(scannerId)
        case 'details':
            return urls.replayVisionScannerDetails(scannerId)
        case 'configure':
            return urls.replayVisionScannerConfigure(scannerId)
        case 'triggers':
            return urls.replayVisionScannerTriggers(scannerId)
        case 'budget':
            return urls.replayVisionScannerBudget(scannerId)
    }
}

/** The history entries one editor visit occupies, by kea-router's per-entry `count`. */
interface EditorHistory {
    scannerId: string
    counts: number[]
    enteredFromApp: boolean
}

interface RouterPayload {
    method?: string
    initial?: boolean
}

const LEAVE_EDITOR_POPSTATE_TIMEOUT_MS = 10000

// The goal flow's overview sits outside the manual stepper. Membership only, so either arm's order works.
const EDITOR_PATH_SEGMENTS = new Set<string>([...SCANNER_EDITOR_STEPS, 'overview'])

export function isScannerEditorPath(pathname: string): boolean {
    const [root, , segment, ...rest] = removeProjectIdIfPresent(pathname).split('/').slice(1)
    return root === 'replay-vision' && rest.length === 0 && EDITOR_PATH_SEGMENTS.has(segment)
}

function currentHistoryCount(): number | null {
    const count = window.history.state?.count
    return typeof count === 'number' ? count : null
}

function trackEditorHistory(
    previous: EditorHistory | null,
    scannerId: string,
    payload: RouterPayload
): EditorHistory | null {
    const count = currentHistoryCount()
    if (count === null) {
        return null
    }
    // On mount kea-router reports an initial POP, so the router's last method says how we got here.
    const method = payload.initial ? router.values.lastMethod : payload.method
    if (!previous || previous.scannerId !== scannerId) {
        return { scannerId, counts: [count], enteredFromApp: method === 'PUSH' }
    }
    if (method === 'PUSH') {
        return { ...previous, counts: [...previous.counts, count] }
    }
    if (method === 'REPLACE') {
        return { ...previous, counts: [...previous.counts.slice(0, -1), count] }
    }
    const index = previous.counts.indexOf(count)
    return index === -1
        ? { scannerId, counts: [count], enteredFromApp: false }
        : { ...previous, counts: previous.counts.slice(0, index + 1) }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scannerEditorSceneLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    breadcrumbs: Breadcrumb[]
    isNew: boolean
    recordingsFirst: boolean
    scannerId: string
    step: ScannerEditorStep
    stepLabels: Record<ScannerEditorStep, string>
    stepperSteps: GuidedWizardStep<ScannerEditorStep>[]
    steps: readonly ScannerEditorStep[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scannerEditorSceneLogicActions {
    loadTags: () => {
        value: true
    } // tagsModel
    leaveEditor: (destination: string) => {
        destination: string
    }
    setScannerId: (scannerId: string) => {
        scannerId: string
    }
    setStep: (step: ScannerEditorStep) => {
        step: ScannerEditorStep
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scannerEditorSceneLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        isNew: (scannerId: string) => boolean
        recordingsFirst: (isNew: boolean, featureFlags: FeatureFlagsSet) => boolean
        steps: (recordingsFirst: boolean) => readonly ScannerEditorStep[]
        stepLabels: (recordingsFirst: boolean) => Record<ScannerEditorStep, string>
        stepperSteps: (recordingsFirst: boolean) => GuidedWizardStep<ScannerEditorStep>[]
        breadcrumbs: (
            scannerId: string,
            isNew: boolean,
            step: ScannerEditorStep,
            stepLabels: Record<ScannerEditorStep, string>,
            searchParams: Record<string, any>
        ) => Breadcrumb[]
    }
    __keaTypeGenInternalReducerActions: {
        'location changed (kea.router)': ({
            method,
            pathname,
            search,
            searchParams,
            hash,
            hashParams,
            initial,
            url,
            routerState,
        }: LocationChangedPayload) => {
            payload: {
                hash: string
                hashParams: Record<string, any>
                initial: boolean
                method: 'POP' | 'PUSH' | 'REPLACE'
                pathname: string
                routerState: Record<string, any>
                search: string
                searchParams: Record<string, any>
                url: string
            }
            type: 'location changed (kea.router)'
        }
    }
}

export type scannerEditorSceneLogicType = MakeLogicType<
    scannerEditorSceneLogicValues,
    scannerEditorSceneLogicActions,
    Record<string, any>,
    scannerEditorSceneLogicMeta
>

export const scannerEditorSceneLogic = kea<scannerEditorSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'scannerEditorSceneLogic']),

    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
        actions: [tagsModel, ['loadTags']],
    })),

    actions({
        setScannerId: (scannerId: string) => ({ scannerId }),
        setStep: (step: ScannerEditorStep) => ({ step }),
        leaveEditor: (destination: string) => ({ destination }),
    }),

    reducers({
        scannerId: [
            'new' as string,
            {
                setScannerId: (_, { scannerId }) => scannerId,
            },
        ],
        step: [
            'configure' as ScannerEditorStep,
            {
                setStep: (_, { step }) => step,
            },
        ],
    }),

    selectors({
        isNew: [(s) => [s.scannerId], (scannerId: string): boolean => scannerId === 'new'],
        // Creation only, so the experiment exposes people who start a scanner rather than everyone who edits one.
        recordingsFirst: [
            (s) => [s.isNew, s.featureFlags],
            (isNew: boolean, featureFlags: FeatureFlagsSet): boolean =>
                isNew && featureFlags[FEATURE_FLAGS.VISION_SCANNER_WIZARD_RECORDINGS_FIRST] === 'test',
        ],
        steps: [
            (s) => [s.recordingsFirst],
            (recordingsFirst: boolean): readonly ScannerEditorStep[] => scannerEditorSteps(recordingsFirst),
        ],
        stepLabels: [
            (s) => [s.recordingsFirst],
            (recordingsFirst: boolean): Record<ScannerEditorStep, string> => scannerStepLabels(recordingsFirst),
        ],
        stepperSteps: [
            (s) => [s.recordingsFirst],
            (recordingsFirst: boolean): GuidedWizardStep<ScannerEditorStep>[] => scannerStepperSteps(recordingsFirst),
        ],
        breadcrumbs: [
            (s) => [s.scannerId, s.isNew, s.step, s.stepLabels, router.selectors.searchParams],
            (
                scannerId: string,
                isNew: boolean,
                step: ScannerEditorStep,
                stepLabels: Record<ScannerEditorStep, string>,
                searchParams: Record<string, any>
            ): Breadcrumb[] => {
                const crumbs: Breadcrumb[] = [VISION_ROOT_BREADCRUMB]
                if (isNew) {
                    // The back arrow targets the second-to-last crumb, so past the goal step the
                    // 'New scanner' crumb points at the goal step and the current step trails it.
                    crumbs.push({
                        key: 'new-scanner',
                        name: 'New scanner',
                        path: scannerStepUrlWithParams('goal', scannerId, searchParams),
                    })
                    if (step !== 'goal') {
                        // Editing a section reached from the goal overview: slot the overview in as the
                        // back target, so leaving the edit returns there rather than to the goal step.
                        if (searchParams.from === 'overview' && step !== 'overview') {
                            const { from: _from, ...overviewParams } = searchParams
                            crumbs.push({
                                key: 'new-scanner-overview',
                                name: stepLabels.overview,
                                path: scannerStepUrlWithParams('overview', scannerId, overviewParams),
                            })
                        }
                        crumbs.push({ key: 'new-scanner-step', name: stepLabels[step] })
                    }
                    return crumbs
                }
                // Editing an existing scanner: the back arrow returns to the scanner tab the edit started from.
                const returnTab = searchParams[EDITOR_RETURN_TAB_PARAM]
                crumbs.push(
                    scannerBreadcrumb(scannerId, null, typeof returnTab === 'string' ? { tab: returnTab } : {}),
                    {
                        key: `scanner-${scannerId}-edit`,
                        name: 'Edit',
                        path: urls.replayVisionScannerConfigure(scannerId),
                    }
                )
                return crumbs
            },
        ],
    }),

    listeners(({ cache }) => ({
        // Unwind the editor's history entries so browser back skips the finished wizard; replace when nothing known precedes it.
        leaveEditor: ({ destination }) => {
            const history: EditorHistory | null = cache.editorHistory
            cache.editorHistory = null
            if (!history?.enteredFromApp || history.counts[history.counts.length - 1] !== currentHistoryCount()) {
                router.actions.replace(destination)
                return
            }
            const depth = history.counts.length
            // Not a disposable, because the scene unmounts during this popstate and would remove it first.
            // The timeout drops the listener if the popstate never comes, so it can't fire on a later back.
            const landed = new AbortController()
            // The entry before the editor holds the count just below the editor's first entry.
            const preEditorCount = history.counts[0] - 1
            window.addEventListener(
                'popstate',
                () => {
                    landed.abort()
                    const target = combineUrl(destination)
                    const landedAt = removeProjectIdIfPresent(window.location.pathname) + window.location.search
                    // kea-router stores no count on a tab's first entry and numbers the next push 1, so null means 0.
                    if (
                        (currentHistoryCount() ?? 0) === preEditorCount &&
                        landedAt !== target.pathname + target.search
                    ) {
                        router.actions.push(destination)
                    }
                },
                { signal: landed.signal }
            )
            setTimeout(() => landed.abort(), LEAVE_EDITOR_POPSTATE_TIMEOUT_MS)
            window.history.go(-depth)
        },
        [router.actionTypes.locationChanged]: ({ pathname }) => {
            if (!isScannerEditorPath(pathname)) {
                cache.editorHistory = null
            }
        },
    })),

    urlToAction(({ actions, values, cache }) => {
        const openStep =
            (step: ScannerEditorStep) =>
            ({ id }: Record<string, string | undefined>, _: unknown, __: unknown, payload: RouterPayload): void => {
                const scannerId = id || 'new'
                cache.editorHistory = trackEditorHistory(cache.editorHistory, scannerId, payload)
                if (scannerId !== values.scannerId) {
                    actions.setScannerId(scannerId)
                }
                if (values.step !== step) {
                    actions.setStep(step)
                }
            }
        return {
            [urls.replayVisionScannerGoal(':id')]: (params, searchParams, hashParams, payload) => {
                if (params.id && params.id !== 'new') {
                    router.actions.replace(urls.replayVisionScannerDetails(params.id))
                    return
                }
                openStep('goal')(params, searchParams, hashParams, payload)
            },
            [urls.replayVisionScannerOverview(':id')]: openStep('overview'),
            [urls.replayVisionScannerDetails(':id')]: openStep('details'),
            [urls.replayVisionScannerConfigure(':id')]: openStep('configure'),
            [urls.replayVisionScannerTriggers(':id')]: openStep('triggers'),
            [urls.replayVisionScannerBudget(':id')]: openStep('budget'),
        }
    }),

    afterMount(({ actions }) => {
        // tagsModel is lazy; load it here so a direct visit doesn't start with an empty tags autocomplete.
        actions.loadTags()
    }),
])
