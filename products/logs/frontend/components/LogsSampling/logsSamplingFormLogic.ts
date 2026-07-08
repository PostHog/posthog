import { actions, afterMount, connect, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { FilterLogicalOperator, PropertyGroupFilter, UniversalFiltersGroup } from '~/types'

import { logsSamplingRulesCreate, logsSamplingRulesPartialUpdate } from 'products/logs/frontend/generated/api'
import {
    LogsSamplingRuleApi,
    PatchedLogsSamplingRuleApi,
    RuleTypeEnumApi,
} from 'products/logs/frontend/generated/api.schemas'
import { logsDropRulesSettingsUrl } from 'products/logs/frontend/logsDropRulesSettingsUrl'

import type { logsSamplingFormLogicType } from './logsSamplingFormLogicType'

const EMPTY_FILTER_GROUP: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [],
}

// Burst capacity is not user-configurable — hardcoded to 10× sustained.
const BURST_MULTIPLIER = 10

export type RateLimitUnit = 'KB/s' | 'MB/s' | 'GB/s'

/** Multiplier to convert the chosen unit into the wire-format unit (KB/s). */
const UNIT_TO_KB_PER_S: Record<RateLimitUnit, number> = {
    'KB/s': 1,
    'MB/s': 1000,
    'GB/s': 1_000_000,
}

/** 1 KB/s minimum, 1 GB/s maximum, expressed in the wire-format unit (KB/s). */
export const MIN_RATE_LIMIT_KB_PER_S = 1
export const MAX_RATE_LIMIT_KB_PER_S = 1_000_000

export interface LogsSamplingFormType {
    name: string
    enabled: boolean
    rule_type: RuleTypeEnumApi
    filter_group: UniversalFiltersGroup
    /** User-entered amount in the chosen unit. Fractional values are allowed. */
    rate_limit_amount: string
    rate_limit_unit: RateLimitUnit
}

const DEFAULT_FORM: LogsSamplingFormType = {
    name: '',
    enabled: true,
    rule_type: RuleTypeEnumApi.PathDrop,
    filter_group: EMPTY_FILTER_GROUP,
    rate_limit_amount: '',
    rate_limit_unit: 'MB/s',
}

/** Pick the largest unit that keeps the displayed amount ≥ 1 (and ≤ 999 where possible). */
function chooseDisplayUnit(kbPerSecond: number): { amount: string; unit: RateLimitUnit } {
    if (kbPerSecond >= UNIT_TO_KB_PER_S['GB/s']) {
        return { amount: formatAmount(kbPerSecond / UNIT_TO_KB_PER_S['GB/s']), unit: 'GB/s' }
    }
    if (kbPerSecond >= UNIT_TO_KB_PER_S['MB/s']) {
        return { amount: formatAmount(kbPerSecond / UNIT_TO_KB_PER_S['MB/s']), unit: 'MB/s' }
    }
    return { amount: formatAmount(kbPerSecond), unit: 'KB/s' }
}

/** Strip trailing zeros after a decimal point so 1500 KB/s round-trips as "1.5 MB/s", not "1.500000". */
function formatAmount(value: number): string {
    if (!Number.isFinite(value)) {
        return ''
    }
    return Number(value.toFixed(6)).toString()
}

/** Convert a user-entered amount + unit into KB/s, rounded to the nearest integer. Returns NaN on invalid input. */
export function rateLimitAmountToKbPerSecond(amount: string, unit: RateLimitUnit): number {
    const parsed = parseFloat(amount.trim())
    if (!Number.isFinite(parsed) || parsed <= 0) {
        return Number.NaN
    }
    return Math.round(parsed * UNIT_TO_KB_PER_S[unit])
}

/** Read either the wrapped `{type, values: [innerGroup]}` (logs-viewer/alerts shape) or the bare inner group. */
function extractFilterGroup(stored: unknown): UniversalFiltersGroup {
    if (!stored || typeof stored !== 'object') {
        return EMPTY_FILTER_GROUP
    }
    const candidate = stored as { type?: unknown; values?: unknown[] }
    if (!Array.isArray(candidate.values)) {
        return EMPTY_FILTER_GROUP
    }
    const first = candidate.values[0] as { type?: unknown; values?: unknown[] } | undefined
    if (first && Array.isArray(first.values) && typeof first.type === 'string') {
        return first as UniversalFiltersGroup
    }
    return candidate as UniversalFiltersGroup
}

/** Wrap inner group as the alerts / logs-viewer wire format expects. */
function wrapFilterGroup(inner: UniversalFiltersGroup): UniversalFiltersGroup {
    return { type: FilterLogicalOperator.And, values: [inner] as never }
}

function isFilterGroupNonEmpty(group: UniversalFiltersGroup): boolean {
    return Array.isArray(group.values) && group.values.length > 0
}

export function buildSamplingFormDefaults(rule: LogsSamplingRuleApi | null): LogsSamplingFormType {
    if (!rule) {
        return { ...DEFAULT_FORM }
    }
    // Legacy SEVERITY_SAMPLING rules collapse into PathDrop — the new form unifies
    // severity into the filter group, so the dedicated severity rule type is no longer surfaced.
    const rule_type = rule.rule_type === RuleTypeEnumApi.SeveritySampling ? RuleTypeEnumApi.PathDrop : rule.rule_type
    const cfg = (rule.config ?? {}) as Record<string, unknown>
    const form: LogsSamplingFormType = {
        ...DEFAULT_FORM,
        name: rule.name,
        enabled: rule.enabled ?? false,
        rule_type,
    }
    form.filter_group = extractFilterGroup(cfg.filter_group)
    if (rule_type === RuleTypeEnumApi.RateLimit) {
        // Read the byte-rate field the ingestion worker enforces on (`kb_per_second`).
        // Fall back to the legacy `logs_per_second` field for rules saved before this
        // fix so they still populate the form — the stored number was always derived as
        // KB/s, and re-saving rewrites it to `kb_per_second`.
        const stored = typeof cfg.kb_per_second === 'number' ? cfg.kb_per_second : cfg.logs_per_second
        if (typeof stored === 'number' && Number.isFinite(stored) && stored > 0) {
            const { amount, unit } = chooseDisplayUnit(stored)
            form.rate_limit_amount = amount
            form.rate_limit_unit = unit
        }
    }
    return form
}

export function buildSamplingConfigPayload(form: LogsSamplingFormType): Record<string, unknown> {
    if (form.rule_type === RuleTypeEnumApi.RateLimit) {
        // The form expresses a byte rate (KB/s · MB/s · GB/s) and the preview plots the
        // threshold in bytes — so the rule must be stored in byte mode (`kb_per_second`),
        // which charges each log its own uncompressed size. Writing `logs_per_second`
        // here silently enforced a records-per-second cap instead, ignoring the chosen unit.
        const kbPerSecond = rateLimitAmountToKbPerSecond(form.rate_limit_amount, form.rate_limit_unit)
        return {
            kb_per_second: kbPerSecond,
            burst_kb: kbPerSecond * BURST_MULTIPLIER,
            filter_group: wrapFilterGroup(form.filter_group),
        }
    }
    return {
        filter_group: wrapFilterGroup(form.filter_group),
    }
}

export interface LogsSamplingFormLogicProps {
    rule: LogsSamplingRuleApi | null
}

export const logsSamplingFormLogic = kea<logsSamplingFormLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsSampling', 'logsSamplingFormLogic']),
    props({} as LogsSamplingFormLogicProps),
    key(({ rule }) => rule?.id ?? 'new'),

    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
    })),

    actions({
        refreshFilterPreview: true,
    }),

    loaders(({ values }) => ({
        filterPreview: [
            null as { time: string; service: string; count: number; bytes_uncompressed?: number }[] | null,
            {
                loadFilterPreview: async (_, breakpoint) => {
                    await breakpoint(400)
                    const form = values.samplingForm
                    if (!isFilterGroupNonEmpty(form.filter_group)) {
                        return null
                    }
                    const response = await api.logs.sparkline({
                        query: {
                            dateRange: { date_from: '-24h', date_to: null },
                            filterGroup: wrapFilterGroup(form.filter_group) as PropertyGroupFilter,
                            severityLevels: [],
                            serviceNames: [],
                            sparklineBreakdownBy: 'service',
                        },
                    })
                    // The backend returns each row keyed by the breakdown value ('service' here),
                    // not by the underlying column name (service_name).
                    return response as {
                        time: string
                        service: string
                        count: number
                        bytes_uncompressed?: number
                    }[]
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        refreshFilterPreview: () => {
            actions.loadFilterPreview(null)
        },
        setSamplingFormValue: ({ name }) => {
            if (name === 'filter_group') {
                actions.refreshFilterPreview()
            }
        },
    })),

    afterMount(({ actions, values }) => {
        // Kick off an initial preview load on mount whenever the form is opened with
        // a filter_group already set (edit mode, or pre-filled defaults). Without this
        // the loader only fires on subsequent edits, leaving the sparkline stuck on
        // "loading" because filterPreview is null and we never ran the request.
        if (isFilterGroupNonEmpty(values.samplingForm.filter_group)) {
            actions.refreshFilterPreview()
        }
    }),

    forms(({ props, values }) => ({
        samplingForm: {
            defaults: buildSamplingFormDefaults(props.rule),
            errors: (form: LogsSamplingFormType) => {
                let rateAmountError: string | undefined
                if (form.rule_type === RuleTypeEnumApi.RateLimit) {
                    if (form.rate_limit_amount.trim() === '') {
                        rateAmountError = 'Enter a rate limit'
                    } else {
                        const parsed = parseFloat(form.rate_limit_amount.trim())
                        const kbPerSecond = rateLimitAmountToKbPerSecond(form.rate_limit_amount, form.rate_limit_unit)
                        if (!Number.isFinite(parsed) || parsed <= 0) {
                            rateAmountError = 'Enter a positive number'
                        } else if (parsed > 999) {
                            rateAmountError = 'Value must be at most 999 — switch to a larger unit if needed'
                        } else if (kbPerSecond < MIN_RATE_LIMIT_KB_PER_S) {
                            rateAmountError = 'Minimum rate limit is 1 KB/s'
                        } else if (kbPerSecond > MAX_RATE_LIMIT_KB_PER_S) {
                            rateAmountError = 'Maximum rate limit is 1 GB/s'
                        }
                    }
                }
                // kea-forms types scalar `errors` per field — filter_group is an object,
                // so its validation lives in `samplingFormSaveDisabledReason` (consumed by
                // the scene's submit button) and is displayed inline via the
                // `filterGroupError` selector below.
                return {
                    name: !form.name?.trim() ? 'Name is required' : undefined,
                    rate_limit_amount: rateAmountError,
                }
            },
            submit: async (form: LogsSamplingFormType) => {
                const projectId = String(values.currentTeamId)
                try {
                    const scope_attribute_filters = (props.rule?.scope_attribute_filters ??
                        []) as PatchedLogsSamplingRuleApi['scope_attribute_filters']
                    const payload = {
                        name: form.name.trim(),
                        enabled: form.enabled,
                        rule_type: form.rule_type,
                        scope_service: null,
                        // scope_path_pattern is folded into the filter group; the backend column will be retired in PR 2.
                        scope_path_pattern: null,
                        scope_attribute_filters,
                        config: buildSamplingConfigPayload(form),
                    }
                    if (props.rule) {
                        const patch: PatchedLogsSamplingRuleApi = payload
                        await logsSamplingRulesPartialUpdate(projectId, props.rule.id, patch)
                        lemonToast.success('Drop rule updated')
                    } else {
                        await logsSamplingRulesCreate(projectId, payload as never)
                        lemonToast.success('Drop rule created')
                    }
                    router.actions.push(logsDropRulesSettingsUrl())
                } catch (e: any) {
                    lemonToast.error(e?.detail ?? e?.message ?? 'Failed to save rule')
                    throw e
                }
            },
        },
    })),
])
