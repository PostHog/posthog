import { actions, connect, kea, key, listeners, path, props } from 'kea'
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

// Burst capacity is no longer user-configurable — hardcoded to 10× sustained.
// Backend follow-up will revisit this alongside the kB/s unit change.
const BURST_MULTIPLIER = 10

export interface LogsSamplingFormType {
    name: string
    enabled: boolean
    rule_type: RuleTypeEnumApi
    filter_group: UniversalFiltersGroup
    rate_limit_logs_per_second: string
}

const DEFAULT_FORM: LogsSamplingFormType = {
    name: '',
    enabled: true,
    rule_type: RuleTypeEnumApi.PathDrop,
    filter_group: EMPTY_FILTER_GROUP,
    rate_limit_logs_per_second: '',
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
        form.rate_limit_logs_per_second =
            typeof cfg.logs_per_second === 'number' && !Number.isNaN(cfg.logs_per_second)
                ? String(cfg.logs_per_second)
                : ''
    }
    return form
}

export function buildSamplingConfigPayload(form: LogsSamplingFormType): Record<string, unknown> {
    if (form.rule_type === RuleTypeEnumApi.RateLimit) {
        const lps = parseInt(form.rate_limit_logs_per_second.trim(), 10)
        return {
            logs_per_second: lps,
            burst_logs: lps * BURST_MULTIPLIER,
            filter_group: wrapFilterGroup(form.filter_group),
        }
    }
    // `patterns: []` keeps the existing path_drop config validator happy.
    // Backend filter_group evaluation is wired in the follow-up PR; today the
    // worker reads `patterns` only, so rules saved through the new UI are
    // no-ops on the ingestion path until that lands.
    return {
        patterns: [],
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
            null as { time: string; service_name: string; count: number }[] | null,
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
                            sparklineBreakdownBy: 'service',
                        },
                    })
                    return response as { time: string; service_name: string; count: number }[]
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

    forms(({ props, values }) => ({
        samplingForm: {
            defaults: buildSamplingFormDefaults(props.rule),
            errors: (form: LogsSamplingFormType) => {
                const lps = parseInt(form.rate_limit_logs_per_second.trim(), 10)
                return {
                    name: !form.name?.trim() ? 'Name is required' : undefined,
                    filter_group: !isFilterGroupNonEmpty(form.filter_group)
                        ? 'Add at least one filter to match logs'
                        : undefined,
                    rate_limit_logs_per_second:
                        form.rule_type === RuleTypeEnumApi.RateLimit &&
                        (form.rate_limit_logs_per_second.trim() === '' || Number.isNaN(lps) || lps < 1)
                            ? 'Enter kilobytes per second (integer ≥ 1)'
                            : undefined,
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
