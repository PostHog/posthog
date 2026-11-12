import type {
    EndExperimentBody,
    ExperimentApi,
    ExperimentConclusionApi,
    ExperimentFlagCleanupTargetApi,
    ShipVariantBody,
} from '@/api/experiments'
import type { ProjectScope } from '@/api/reports'
import { formatMonthDay } from '@/lib/dates'
import { isRecord } from '@/lib/records'

import { CONCLUSION_COPY } from './conclusionCopy'
import { type ChangeUnit, changeUnitOf, formatDelta, metricDefsOf } from './detailModel'
import {
    type ExperimentMethod,
    methodOf,
    type PrimaryResult,
    shippedVariantOf,
    suggestedConclusion,
    type VariantResult,
    variantKeysOf,
} from './experimentModel'

// The finish sheet mirrors the web's `FinishExperimentModal` (`ExperimentModals.tsx`): one form for Ship and End, the
// same disabled reasons in the same order, and the same request bodies (`experimentLogic` `finishExperiment` and
// `endExperiment`). Ship and End are presets of it, not two forms.

export type FinishPreset = 'ship' | 'end'
export type ReleaseMode = 'population' | 'everyone'

export const COMMENT_MAX_LENGTH = 4000

export interface FinishForm {
    preset: FinishPreset
    /** Null ends without rolling out a variant, like an empty select on the web. */
    variant: string | null
    release: ReleaseMode
    conclusion: ExperimentConclusionApi | null
    comment: string
    cleanup: boolean
    /** The pick when the server cannot tell which repository to use (`source: ambiguous`). */
    repository: string | null
}

/** What the sheet needs to know about the experiment. Read once when it opens. */
export interface FinishContext {
    name: string
    flagKey: string
    /** Every variant on the flag, control included, in flag order. */
    variants: string[]
    controlKey: string
    /** The variant the web's `isSingleVariantShipped` finds at 100% for everyone, or null. */
    rolledOut: string | null
    frozen: boolean
    canShip: boolean
    /** `users`, or `groups` for a group-aggregated flag. */
    noun: string
    leader: string | null
    /** The leader is ahead in the metric's good direction, so the sheet may call it leading. */
    leaderAhead: boolean
    suggested: ExperimentConclusionApi | null
    changeUnit: ChangeUnit
}

interface FlagGroupShape {
    properties?: unknown
    rollout_percentage?: unknown
    exposure_frozen?: unknown
}

interface FlagVariantShape {
    key: string
    rollout_percentage?: unknown
}

function flagFilters(experiment: ExperimentApi): Record<string, unknown> {
    const filters = experiment.feature_flag?.filters
    return isRecord(filters) ? filters : {}
}

function flagGroups(experiment: ExperimentApi): FlagGroupShape[] {
    const groups = flagFilters(experiment).groups
    return Array.isArray(groups) ? groups.filter(isRecord) : []
}

function flagVariants(experiment: ExperimentApi): FlagVariantShape[] {
    const multivariate = flagFilters(experiment).multivariate
    const variants = isRecord(multivariate) ? multivariate.variants : undefined
    if (!Array.isArray(variants)) {
        return []
    }
    return variants.filter(
        (variant): variant is FlagVariantShape => isRecord(variant) && typeof variant.key === 'string'
    )
}

/** The web's `isSingleVariantShipped` + `getShippedVariantKey`: one variant at 100% for everyone, on an active flag. */
export function rolledOutVariantOf(experiment: ExperimentApi): string | null {
    if (!experiment.feature_flag || experiment.feature_flag.active === false) {
        return null
    }
    const first = flagGroups(experiment)[0]
    if (!first || !Array.isArray(first.properties) || first.properties.length > 0 || first.rollout_percentage !== 100) {
        return null
    }
    return flagVariants(experiment).find((variant) => variant.rollout_percentage === 100)?.key ?? null
}

/** The web's `hasFrozenExposureStamps`. */
export function hasFrozenExposure(experiment: ExperimentApi): boolean {
    return flagGroups(experiment).some((group) => group.exposure_frozen === true)
}

/**
 * The web names the group type, such as "organizations". The app does not read group types, so a group-aggregated
 * flag says "groups".
 */
export function audienceNoun(experiment: ExperimentApi): string {
    const index = flagFilters(experiment).aggregation_group_type_index
    return index === null || index === undefined ? 'users' : 'groups'
}

/**
 * Negative when `a` is the better pick to ship. A p-value has no direction, so the Frequentist order puts variants that
 * move the metric the right way first: better and significant, better, worse, then worse and significant. Inside a
 * group a lower p-value is stronger evidence, which goes first for a better variant and last for a worse one. Chance
 * to win already includes the direction. A variant without results goes last.
 */
function compareForShipping(
    a: VariantResult | undefined,
    b: VariantResult | undefined,
    method: ExperimentMethod
): number {
    if (!a || !b) {
        return (a ? 0 : 1) - (b ? 0 : 1)
    }
    if (method !== 'freq') {
        return (b.chanceToWin ?? 0) - (a.chanceToWin ?? 0)
    }
    const rank = (result: VariantResult): number =>
        result.better ? (result.significant ? 0 : 1) : result.significant ? 3 : 2
    const byP = (a.pValue ?? 1) - (b.pValue ?? 1)
    return rank(a) - rank(b) || (a.better ? byP : -byP)
}

export function finishContextOf(
    experiment: ExperimentApi,
    primary: PrimaryResult | null,
    method: ExperimentMethod = methodOf(experiment)
): FinishContext {
    const variants = variantKeysOf(experiment)
    const leader = primary
        ? ([...primary.variants]
              .filter((variant) => variants.includes(variant.key))
              .sort((a, b) => compareForShipping(a, b, method))[0] ?? null)
        : null
    return {
        name: experiment.name,
        flagKey: experiment.feature_flag?.key ?? experiment.feature_flag_key,
        variants,
        controlKey: primary?.baseline.key ?? 'control',
        rolledOut: rolledOutVariantOf(experiment),
        frozen: hasFrozenExposure(experiment),
        canShip: experiment.feature_flag_rule_id == null,
        noun: audienceNoun(experiment),
        leader: leader?.key ?? null,
        leaderAhead: leader?.better === true,
        suggested: suggestedConclusion(primary),
        changeUnit: changeUnitOf(
            primary?.variants[0]?.differenceType ?? 'relative',
            metricDefsOf(experiment).primary[0]?.kind ?? 'mean'
        ),
    }
}

/** Ship: the leader, the experiment population and Won. End: no variant and the conclusion the results suggest. */
export function initialFinishForm(preset: FinishPreset, context: FinishContext): FinishForm {
    const ships = preset === 'ship' && context.canShip && !context.rolledOut
    const firstTest = context.variants.find((key) => key !== context.controlKey) ?? null
    return {
        preset,
        variant: ships ? (context.leader ?? firstTest) : null,
        release: 'population',
        conclusion: preset === 'ship' ? 'won' : context.suggested,
        comment: '',
        cleanup: false,
        repository: null,
    }
}

export type FinishFormAction =
    | { type: 'variant'; variant: string | null }
    | { type: 'release'; release: ReleaseMode }
    | { type: 'conclusion'; conclusion: ExperimentConclusionApi }
    | { type: 'comment'; comment: string }
    | { type: 'cleanup'; cleanup: boolean }
    | { type: 'repository'; repository: string }
    | { type: 'reset'; form: FinishForm }

export function finishFormReducer(form: FinishForm, action: FinishFormAction): FinishForm {
    switch (action.type) {
        case 'variant':
            return { ...form, variant: action.variant }
        case 'release':
            return { ...form, release: action.release }
        case 'conclusion':
            return { ...form, conclusion: action.conclusion }
        case 'comment':
            return { ...form, comment: action.comment.slice(0, COMMENT_MAX_LENGTH) }
        case 'cleanup':
            return { ...form, cleanup: action.cleanup }
        case 'repository':
            return { ...form, repository: action.repository }
        case 'reset':
            return action.form
    }
}

/**
 * The repository a cleanup PR would target (`GET flag_cleanup_target/`). `unavailable` hides the cleanup row: the
 * session's grant lacks `task:write`, which `open_cleanup_pr` needs.
 */
export type CleanupTargetState =
    | { status: 'unavailable' }
    | { status: 'loading' }
    | { status: 'error' }
    | { status: 'ready'; target: ExperimentFlagCleanupTargetApi }

function cleanupWanted(form: FinishForm, cleanup: CleanupTargetState): boolean {
    if (!form.cleanup || cleanup.status === 'unavailable') {
        return false
    }
    return cleanup.status !== 'ready' || cleanup.target.source !== 'no_integration'
}

/** The web's `disabledReason`, in its order. Null when the primary button can go. */
export function finishDisabledReason(form: FinishForm, cleanup: CleanupTargetState): string | null {
    if (!form.conclusion) {
        return 'Select a conclusion'
    }
    if (!cleanupWanted(form, cleanup)) {
        return null
    }
    if (cleanup.status === 'loading') {
        return 'Checking which repository the cleanup PR would target'
    }
    if (cleanup.status === 'error') {
        return "Couldn't check which repository the cleanup PR would target"
    }
    if (cleanup.status === 'ready' && cleanup.target.source === 'ambiguous' && !form.repository) {
        return 'Select a repository for the cleanup PR'
    }
    return null
}

/** What sits under the cleanup checkbox. */
export type CleanupNote =
    | { kind: 'none' }
    | { kind: 'no_integration' }
    | { kind: 'loading' }
    | { kind: 'error' }
    | { kind: 'repository'; repository: string }
    | { kind: 'pick'; candidates: string[] }

export function cleanupNoteOf(form: FinishForm, cleanup: CleanupTargetState): CleanupNote {
    if (cleanup.status === 'ready' && cleanup.target.source === 'no_integration') {
        return { kind: 'no_integration' }
    }
    if (!form.cleanup || cleanup.status === 'unavailable') {
        return { kind: 'none' }
    }
    if (cleanup.status === 'loading' || cleanup.status === 'error') {
        return { kind: cleanup.status }
    }
    if (cleanup.target.source === 'ambiguous') {
        return { kind: 'pick', candidates: cleanup.target.candidates }
    }
    return cleanup.target.repository ? { kind: 'repository', repository: cleanup.target.repository } : { kind: 'none' }
}

/** True when the primary button ships a variant rather than only ending. */
export function finishShips(form: FinishForm, context: FinishContext): boolean {
    return context.canShip && form.variant !== null && !context.rolledOut
}

export type FinishRequest =
    | { kind: 'ship'; variant: string; body: ShipVariantBody }
    | { kind: 'end'; body: EndExperimentBody }

/**
 * The body `experimentLogic` sends. `set_repository_as_team_default` is never sent: it needs `project:write`, which the
 * app does not request.
 */
export function finishRequestOf(form: FinishForm, context: FinishContext, cleanup: CleanupTargetState): FinishRequest {
    const openCleanupPr = cleanupWanted(form, cleanup)
    const repository =
        openCleanupPr && cleanup.status === 'ready' && cleanup.target.source === 'ambiguous' ? form.repository : null
    const comment = form.comment.trim()
    const shared = {
        conclusion: form.conclusion,
        conclusion_comment: comment || null,
        open_cleanup_pr: openCleanupPr,
        ...(repository ? { repository } : {}),
    }
    if (context.canShip && form.variant !== null && !context.rolledOut) {
        return {
            kind: 'ship',
            variant: form.variant,
            body: { ...shared, variant_key: form.variant, release_to_everyone: form.release === 'everyone' },
        }
    }
    return { kind: 'end', body: shared }
}

/** A line of copy with one code-styled part, such as a flag key or a variant. */
export interface CodeLine {
    before: string
    code: string | null
    after: string
}

export function finishTitle(form: FinishForm, context: FinishContext): string {
    return form.preset === 'ship' && context.canShip && !context.rolledOut ? 'Ship a variant' : 'End experiment'
}

export function finishDescription(form: FinishForm, context: FinishContext): CodeLine {
    if (context.rolledOut) {
        return { before: `Ends ${context.name}.`, code: null, after: '' }
    }
    if (finishShips(form, context)) {
        return {
            before: `Ends ${context.name} and rolls `,
            code: form.variant,
            after: ' out through its feature flag.',
        }
    }
    return {
        before: `Ends ${context.name}. Results stop updating, and the flag keeps serving its variants until you change it.`,
        code: null,
        after: '',
    }
}

export function finishButtonLabel(form: FinishForm, context: FinishContext, pending: boolean): string {
    const ships = finishShips(form, context)
    if (pending) {
        return ships ? `Shipping ${form.variant}…` : 'Ending…'
    }
    return ships ? `Ship ${form.variant}` : 'End experiment'
}

/** The toast after a finish. A cleanup PR is named only when the server says it opened one. */
export function finishToast(request: FinishRequest, cleanupStarted: boolean): string {
    const done = request.kind === 'ship' ? `Shipped ${request.variant}` : 'Experiment ended'
    return cleanupStarted ? `${done} · cleanup PR started` : done
}

export interface ReleaseOption {
    value: ReleaseMode
    label: string
    recommended: boolean
    description: string
}

export function releaseOptions(noun: string): ReleaseOption[] {
    return [
        {
            value: 'population',
            label: 'Roll out to the experiment population',
            recommended: true,
            description: `Only ${noun} already in the experiment see the variant. Per-user variant overrides still apply.`,
        },
        {
            value: 'everyone',
            label: `Roll out to all ${noun}`,
            recommended: false,
            description: `All ${noun} see the variant, including those outside the experiment. Per-user variant overrides are bypassed.`,
        },
    ]
}

function percent(fraction: number): string {
    return `${(fraction * 100).toFixed(1)}%`
}

function pValueText(value: number): string {
    return value < 0.001 ? 'p < 0.001' : `p = ${value.toFixed(3)}`
}

export interface VariantOption {
    /** Null is the "None" row. */
    key: string | null
    meta: string | null
    leading: boolean
}

/**
 * Test variants with results first, the most likely winner on top, then test variants without results, then control,
 * then "None".
 */
export function variantOptions(
    context: FinishContext,
    primary: PrimaryResult | null,
    method: ExperimentMethod
): VariantOption[] {
    const results = new Map((primary?.variants ?? []).map((variant) => [variant.key, variant]))
    const tests = context.variants
        .filter((key) => key !== context.controlKey)
        .sort((a, b) => compareForShipping(results.get(a), results.get(b), method))
    const rows: VariantOption[] = tests.map((key) => {
        const result = results.get(key)
        let meta = 'No results yet'
        if (result) {
            const stat =
                method === 'freq'
                    ? result.pValue === undefined
                        ? null
                        : pValueText(result.pValue)
                    : result.chanceToWin === undefined
                      ? null
                      : `${percent(result.chanceToWin)} chance to win`
            const change = formatDelta(result.delta, context.changeUnit)
            meta = stat ? `${stat} · ${change}` : change
        }
        return { key, meta, leading: key === context.leader && context.leaderAhead }
    })
    if (context.variants.includes(context.controlKey)) {
        rows.push({ key: context.controlKey, meta: 'Keep the current experience', leading: false })
    }
    rows.push({ key: null, meta: null, leading: false })
    return rows
}

function groupNumber(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** "Annual plan toggle default starts now. The flag `annual-plan-toggle` goes live for 100% of its audience, split 50 / 50." */
export function launchDescription(experiment: ExperimentApi): CodeLine {
    const groups = flagGroups(experiment)
    const split = flagVariants(experiment)
        .map((variant) => groupNumber(variant.rollout_percentage))
        .filter((share): share is number => share !== null)
    const splitText = split.length > 1 ? `, split ${split.join(' / ')}` : ''
    const rollout = groups.length === 1 ? (groupNumber(groups[0]?.rollout_percentage) ?? 100) : null
    const audience = rollout === null ? 'its release conditions' : `${rollout}% of its audience`
    return {
        before: `${experiment.name} starts now. The flag `,
        code: experiment.feature_flag?.key ?? experiment.feature_flag_key,
        after: ` goes live for ${audience}${splitText}.`,
    }
}

function dayOf(iso: string | null | undefined): string | null {
    const parsed = iso ? Date.parse(iso) : Number.NaN
    return Number.isNaN(parsed) ? null : formatMonthDay(new Date(parsed))
}

/** What the action bar says on a complete experiment, which has no verbs left. */
export function completionLine(experiment: ExperimentApi): { label: string; line: string } {
    const conclusion = experiment.conclusion ? CONCLUSION_COPY[experiment.conclusion].label : 'Complete'
    const day = dayOf(experiment.end_date)
    const shipped = shippedVariantOf(experiment)
    if (shipped) {
        return { label: conclusion, line: day ? `${shipped} shipped ${day}` : `${shipped} shipped` }
    }
    return { label: conclusion, line: day ? `Ended ${day}, nothing shipped` : 'Nothing shipped' }
}

export function editConclusionDescription(experiment: ExperimentApi): string {
    const day = dayOf(experiment.end_date)
    const ended = day ? `${experiment.name} ended ${day}.` : `${experiment.name} has ended.`
    return `${ended} Changing the conclusion does not change the feature flag.`
}

export function webApprovalUrl(scope: ProjectScope | null, changeRequestId: string): string | undefined {
    if (!scope) {
        return undefined
    }
    return `${scope.host.replace(/\/+$/, '')}/project/${scope.projectId}/approvals/${encodeURIComponent(changeRequestId)}`
}
