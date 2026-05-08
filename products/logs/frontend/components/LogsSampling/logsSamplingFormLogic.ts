import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import {
    logsSamplingRulesCreate,
    logsSamplingRulesPartialUpdate,
    logsSamplingRulesSimulateCreate,
    logsServicesCreate,
} from 'products/logs/frontend/generated/api'
import {
    _LogsSparklineBucketApi,
    LogsSamplingRuleApi,
    PatchedLogsSamplingRuleApi,
    RuleTypeEnumApi,
} from 'products/logs/frontend/generated/api.schemas'
import { logsDropRulesSettingsUrl } from 'products/logs/frontend/logsDropRulesSettingsUrl'

import type { logsSamplingFormLogicType } from './logsSamplingFormLogicType'

/** Inner group held in form state. The API wire format wraps this in another { type, values: [innerGroup] }. */
const EMPTY_DROP_FILTER_GROUP: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [],
}

export interface LogsSamplingFormType {
    name: string
    enabled: boolean
    rule_type: RuleTypeEnumApi
    scope_service: string
    path_drop_filter_group: UniversalFiltersGroup
    rate_limit_logs_per_second: string
    rate_limit_burst_logs: string
}

const DEFAULT_FORM: LogsSamplingFormType = {
    name: '',
    enabled: true,
    rule_type: RuleTypeEnumApi.PathDrop,
    scope_service: '',
    path_drop_filter_group: EMPTY_DROP_FILTER_GROUP,
    rate_limit_logs_per_second: '',
    rate_limit_burst_logs: '',
}

/** Read either the wrapped `{type, values: [innerGroup]}` (logs-viewer/alerts shape) or the bare inner group. */
function extractFilterGroup(stored: unknown): UniversalFiltersGroup {
    if (!stored || typeof stored !== 'object') {
        return EMPTY_DROP_FILTER_GROUP
    }
    const candidate = stored as { type?: unknown; values?: unknown[] }
    if (!Array.isArray(candidate.values)) {
        return EMPTY_DROP_FILTER_GROUP
    }
    const first = candidate.values[0] as { type?: unknown; values?: unknown[] } | undefined
    if (first && Array.isArray(first.values) && typeof first.type === 'string') {
        return first as UniversalFiltersGroup
    }
    return candidate as UniversalFiltersGroup
}

/** Wrap inner group as the logs-viewer / sparkline endpoint expects: { type: AND, values: [innerGroup] }. */
function wrapFilterGroup(inner: UniversalFiltersGroup): UniversalFiltersGroup {
    return { type: FilterLogicalOperator.And, values: [inner] as never }
}

export function buildSamplingFormDefaults(rule: LogsSamplingRuleApi | null): LogsSamplingFormType {
    if (!rule) {
        return { ...DEFAULT_FORM }
    }
    const form: LogsSamplingFormType = { ...DEFAULT_FORM, name: rule.name, enabled: rule.enabled ?? false }
    // Merge legacy SEVERITY_SAMPLING rules into the unified PathDrop form — the UI no longer distinguishes them.
    form.rule_type =
        rule.rule_type === RuleTypeEnumApi.SeveritySampling ? RuleTypeEnumApi.PathDrop : rule.rule_type
    form.scope_service = rule.scope_service ?? ''
    const cfg = (rule.config ?? {}) as Record<string, unknown>
    if (form.rule_type === RuleTypeEnumApi.PathDrop) {
        form.path_drop_filter_group = extractFilterGroup(cfg.filter_group)
    }
    if (rule.rule_type === RuleTypeEnumApi.RateLimit) {
        form.rate_limit_logs_per_second =
            typeof cfg.logs_per_second === 'number' && !Number.isNaN(cfg.logs_per_second)
                ? String(cfg.logs_per_second)
                : ''
        form.rate_limit_burst_logs =
            typeof cfg.burst_logs === 'number' && !Number.isNaN(cfg.burst_logs) ? String(cfg.burst_logs) : ''
    }
    return form
}

export function buildSamplingConfigPayload(form: LogsSamplingFormType): Record<string, unknown> {
    if (form.rule_type === RuleTypeEnumApi.RateLimit) {
        const lps = parseInt(form.rate_limit_logs_per_second.trim(), 10)
        const out: Record<string, unknown> = { logs_per_second: lps }
        const burst = form.rate_limit_burst_logs.trim()
        if (burst !== '') {
            const b = parseInt(burst, 10)
            if (!Number.isNaN(b)) {
                out.burst_logs = b
            }
        }
        return out
    }
    return {
        // patterns retained as empty list to keep the existing path_drop config validator happy;
        // ingestion is unchanged in this PR — filter-group evaluation will be wired in a follow-up.
        patterns: [],
        filter_group: wrapFilterGroup(form.path_drop_filter_group),
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
        scheduleSimulate: true,
        refreshServiceTraffic: true,
        refreshDropPreview: true,
    }),

    loaders(({ values, props }) => ({
        simulation: [
            null as { estimated_reduction_pct: number; notes: string } | null,
            {
                runSimulateNow: async () => {
                    if (
                        !props.rule?.id ||
                        props.rule.rule_type === RuleTypeEnumApi.SeveritySampling ||
                        props.rule.rule_type === RuleTypeEnumApi.RateLimit
                    ) {
                        return null
                    }
                    const projectId = String(values.currentTeamId)
                    return await logsSamplingRulesSimulateCreate(projectId, props.rule.id)
                },
            },
        ],
        dropPreviewSparkline: [
            [] as _LogsSparklineBucketApi[],
            {
                loadDropPreviewSparkline: async (_, breakpoint) => {
                    await breakpoint(500)
                    const form = values.samplingForm
                    if (form.rule_type !== RuleTypeEnumApi.PathDrop) {
                        return []
                    }
                    if (form.path_drop_filter_group.values.length === 0) {
                        return []
                    }
                    const wrapped = wrapFilterGroup(form.path_drop_filter_group)
                    // The /logs/sparkline endpoint returns the bare bucket array (not { results: [...] }) —
                    // the generated client's type is wrong, so use the handwritten api.logs.sparkline instead.
                    const rows = (await api.logs.sparkline({
                        query: {
                            dateRange: { date_from: '-1h', date_to: null },
                            filterGroup: wrapped as never,
                            sparklineBreakdownBy: 'service',
                        } as never,
                    })) as _LogsSparklineBucketApi[]
                    return rows
                },
            },
        ],
        serviceTraffic: [
            null as { log_count: number; avg_logs_per_sec: number } | null,
            {
                loadServiceTraffic: async (_, breakpoint) => {
                    await breakpoint(400)
                    const form = values.samplingForm
                    const svc = form.scope_service.trim()
                    if (!svc) {
                        return null
                    }
                    const projectId = String(values.currentTeamId)
                    const res = await logsServicesCreate(projectId, {
                        query: {
                            dateRange: { date_from: '-24h', date_to: null },
                            serviceNames: [svc],
                        },
                    })
                    const row = res.services.find((s) => s.service_name === svc)
                    if (!row) {
                        return { log_count: 0, avg_logs_per_sec: 0 }
                    }
                    const logCount = row.log_count
                    const avg = logCount / (24 * 3600)
                    return { log_count: logCount, avg_logs_per_sec: avg }
                },
            },
        ],
    })),

    listeners(({ actions, props, cache }) => ({
        refreshServiceTraffic: () => {
            actions.loadServiceTraffic(null)
        },
        refreshDropPreview: () => {
            actions.loadDropPreviewSparkline(null)
        },
        scheduleSimulate: () => {
            if (!props.rule?.id) {
                return
            }
            const w = cache as { simulateTimer?: ReturnType<typeof setTimeout> }
            if (w.simulateTimer) {
                clearTimeout(w.simulateTimer)
            }
            w.simulateTimer = setTimeout(() => {
                actions.runSimulateNow()
            }, 500)
        },
        setSamplingFormValue: () => {
            actions.scheduleSimulate()
            actions.refreshServiceTraffic()
            actions.refreshDropPreview()
        },
        submitSamplingFormSuccess: () => {
            actions.scheduleSimulate()
        },
    })),

    selectors({
        canSimulate: [
            () => [(_, props) => props.rule],
            (rule: LogsSamplingRuleApi | null) =>
                Boolean(rule?.id) &&
                rule?.rule_type !== RuleTypeEnumApi.SeveritySampling &&
                rule?.rule_type !== RuleTypeEnumApi.RateLimit,
        ],
        isNewRule: [() => [(_, props) => props.rule], (rule: LogsSamplingRuleApi | null) => !rule],
    }),

    afterMount(({ actions, props }) => {
        actions.resetSamplingForm(buildSamplingFormDefaults(props.rule))
        if (
            props.rule?.id &&
            props.rule.rule_type !== RuleTypeEnumApi.SeveritySampling &&
            props.rule.rule_type !== RuleTypeEnumApi.RateLimit
        ) {
            actions.scheduleSimulate()
        }
        actions.refreshServiceTraffic()
        actions.refreshDropPreview()
    }),

    forms(({ props, values }) => ({
        samplingForm: {
            defaults: buildSamplingFormDefaults(props.rule),
            errors: (form) => {
                const lps = parseInt(form.rate_limit_logs_per_second.trim(), 10)
                const burstRaw = form.rate_limit_burst_logs.trim()
                const burst = burstRaw === '' ? null : parseInt(burstRaw, 10)
                return {
                    name: !form.name?.trim() ? 'Name is required' : undefined,
                    path_drop_filter_group:
                        form.rule_type === RuleTypeEnumApi.PathDrop &&
                        form.path_drop_filter_group.values.length === 0
                            ? 'Add at least one filter — empty filters would drop every log line.'
                            : undefined,
                    scope_service:
                        form.rule_type === RuleTypeEnumApi.RateLimit && !form.scope_service?.trim()
                            ? 'Select or enter a service name'
                            : undefined,
                    rate_limit_logs_per_second:
                        form.rule_type === RuleTypeEnumApi.RateLimit &&
                        (form.rate_limit_logs_per_second.trim() === '' || Number.isNaN(lps) || lps < 1)
                            ? 'Enter logs per second (integer ≥ 1)'
                            : undefined,
                    rate_limit_burst_logs:
                        form.rule_type === RuleTypeEnumApi.RateLimit &&
                        burstRaw !== '' &&
                        (burst === null || Number.isNaN(burst) || burst < lps)
                            ? 'Burst must be an integer ≥ sustained rate, or leave empty for default'
                            : undefined,
                }
            },
            submit: async (form) => {
                const projectId = String(values.currentTeamId)
                try {
                    const scope_service = form.scope_service.trim() || null
                    const scope_attribute_filters = (props.rule?.scope_attribute_filters ??
                        []) as PatchedLogsSamplingRuleApi['scope_attribute_filters']
                    const payload = {
                        name: form.name.trim(),
                        enabled: form.enabled,
                        rule_type: form.rule_type,
                        scope_service,
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
