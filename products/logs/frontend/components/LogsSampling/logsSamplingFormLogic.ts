import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import {
    logsSamplingRulesCreate,
    logsSamplingRulesPartialUpdate,
    logsSamplingRulesSimulateCreate,
    logsServicesCreate,
} from 'products/logs/frontend/generated/api'
import {
    LogsSamplingRuleApi,
    PatchedLogsSamplingRuleApi,
    RuleTypeEnumApi,
} from 'products/logs/frontend/generated/api.schemas'
import { logsDropRulesSettingsUrl } from 'products/logs/frontend/logsDropRulesSettingsUrl'

import type { logsSamplingFormLogicType } from './logsSamplingFormLogicType'

export type SeverityActionChoice = 'keep' | 'drop' | 'sample'

/** What `path_drop` regex lines are evaluated against (maps to config.match_attribute_key). */
export type PathDropMatchTarget = 'auto_path' | 'custom_attribute'

export interface LogsSamplingFormType {
    name: string
    enabled: boolean
    rule_type: RuleTypeEnumApi
    scope_service: string
    scope_path_pattern: string
    path_drop_match_target: PathDropMatchTarget
    /** When path_drop_match_target is custom_attribute, patterns match only this attribute. */
    path_drop_match_attribute_key: string
    path_drop_patterns: string
    severity_debug: SeverityActionChoice
    severity_debug_rate: number
    severity_info: SeverityActionChoice
    severity_info_rate: number
    severity_warn: SeverityActionChoice
    severity_warn_rate: number
    severity_error: SeverityActionChoice
    severity_error_rate: number
    always_keep_status_gte: string
    always_keep_latency_ms_gt: string
    rate_limit_logs_per_second: string
    rate_limit_burst_logs: string
}

const DEFAULT_FORM: LogsSamplingFormType = {
    name: '',
    enabled: true,
    rule_type: RuleTypeEnumApi.PathDrop,
    scope_service: '',
    scope_path_pattern: '',
    path_drop_match_target: 'auto_path',
    path_drop_match_attribute_key: '',
    path_drop_patterns: '',
    severity_debug: 'keep',
    severity_debug_rate: 0.5,
    severity_info: 'keep',
    severity_info_rate: 0.5,
    severity_warn: 'keep',
    severity_warn_rate: 0.5,
    severity_error: 'keep',
    severity_error_rate: 0.5,
    always_keep_status_gte: '',
    always_keep_latency_ms_gt: '',
    rate_limit_logs_per_second: '',
    rate_limit_burst_logs: '',
}

function parseSeverityPart(
    key: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR',
    actionsObj: Record<string, unknown> | undefined,
    form: LogsSamplingFormType
): void {
    const raw = actionsObj?.[key] as Record<string, unknown> | undefined
    const prefix =
        key === 'DEBUG'
            ? 'severity_debug'
            : key === 'INFO'
              ? 'severity_info'
              : key === 'WARN'
                ? 'severity_warn'
                : 'severity_error'
    if (!raw || typeof raw.type !== 'string') {
        return
    }
    const patch = form as unknown as Record<string, unknown>
    if (raw.type === 'drop') {
        patch[prefix] = 'drop'
    } else if (raw.type === 'sample') {
        // Sampling is not exposed in the UI; coerce legacy configs to keep on load.
        patch[prefix] = 'keep'
    } else {
        patch[prefix] = 'keep'
    }
}

export function buildSamplingFormDefaults(rule: LogsSamplingRuleApi | null): LogsSamplingFormType {
    if (!rule) {
        return { ...DEFAULT_FORM }
    }
    const form: LogsSamplingFormType = { ...DEFAULT_FORM, name: rule.name, enabled: rule.enabled ?? false }
    form.rule_type = rule.rule_type
    form.scope_service = rule.scope_service ?? ''
    form.scope_path_pattern = rule.scope_path_pattern ?? ''
    const cfg = (rule.config ?? {}) as Record<string, unknown>
    if (rule.rule_type === RuleTypeEnumApi.PathDrop) {
        const patterns = (cfg.patterns as string[]) || []
        form.path_drop_patterns = patterns.join('\n')
        const mak = cfg.match_attribute_key
        const makStr = typeof mak === 'string' ? mak : ''
        form.path_drop_match_attribute_key = makStr
        form.path_drop_match_target = makStr.trim() !== '' ? 'custom_attribute' : 'auto_path'
    }
    if (rule.rule_type === RuleTypeEnumApi.SeveritySampling) {
        const actionsObj = cfg.actions as Record<string, unknown> | undefined
        parseSeverityPart('DEBUG', actionsObj, form)
        parseSeverityPart('INFO', actionsObj, form)
        parseSeverityPart('WARN', actionsObj, form)
        parseSeverityPart('ERROR', actionsObj, form)
        const ak = cfg.always_keep as Record<string, unknown> | undefined
        if (ak && typeof ak === 'object') {
            if (typeof ak.status_gte === 'number') {
                form.always_keep_status_gte = String(ak.status_gte)
            }
            if (typeof ak.latency_ms_gt === 'number') {
                form.always_keep_latency_ms_gt = String(ak.latency_ms_gt)
            }
        }
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

function severityActionPayload(choice: SeverityActionChoice, rate: number): Record<string, unknown> {
    if (choice === 'drop') {
        return { type: 'drop' }
    }
    if (choice === 'sample') {
        return { type: 'sample', rate: Math.max(0, Math.min(1, rate)) }
    }
    return { type: 'keep' }
}

export function buildSamplingConfigPayload(form: LogsSamplingFormType): Record<string, unknown> {
    if (form.rule_type === RuleTypeEnumApi.PathDrop) {
        const patterns = form.path_drop_patterns
            .split('\n')
            .map((s) => s.trim())
            .filter(Boolean)
        const key = form.path_drop_match_target === 'custom_attribute' ? form.path_drop_match_attribute_key.trim() : ''
        const out: Record<string, unknown> = { patterns }
        if (key !== '') {
            out.match_attribute_key = key
        }
        return out
    }
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
    const always: Record<string, unknown> = {}
    const sg = form.always_keep_status_gte.trim()
    if (sg !== '') {
        const n = parseInt(sg, 10)
        if (!Number.isNaN(n)) {
            always.status_gte = n
        }
    }
    const lat = form.always_keep_latency_ms_gt.trim()
    if (lat !== '') {
        const n = parseFloat(lat)
        if (!Number.isNaN(n)) {
            always.latency_ms_gt = n
        }
    }
    const out: Record<string, unknown> = {
        actions: {
            DEBUG: severityActionPayload(form.severity_debug, form.severity_debug_rate),
            INFO: severityActionPayload(form.severity_info, form.severity_info_rate),
            WARN: severityActionPayload(form.severity_warn, form.severity_warn_rate),
            ERROR: severityActionPayload(form.severity_error, form.severity_error_rate),
        },
    }
    if (Object.keys(always).length > 0) {
        out.always_keep = always
    }
    return out
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
        serviceTraffic: [
            null as { log_count: number; avg_logs_per_sec: number } | null,
            {
                loadServiceTraffic: async (_, breakpoint) => {
                    await breakpoint(400)
                    const form = values.samplingForm
                    if (form.rule_type !== RuleTypeEnumApi.RateLimit) {
                        return null
                    }
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
                    path_drop_match_attribute_key:
                        form.rule_type === RuleTypeEnumApi.PathDrop &&
                        form.path_drop_match_target === 'custom_attribute' &&
                        !form.path_drop_match_attribute_key?.trim()
                            ? 'Enter the log attribute key (e.g. http.route)'
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
                    const scope_path_pattern =
                        form.rule_type === RuleTypeEnumApi.RateLimit ? null : form.scope_path_pattern.trim() || null
                    const scope_attribute_filters = (props.rule?.scope_attribute_filters ??
                        []) as PatchedLogsSamplingRuleApi['scope_attribute_filters']
                    const payload = {
                        name: form.name.trim(),
                        enabled: form.enabled,
                        rule_type: form.rule_type,
                        scope_service,
                        scope_path_pattern,
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
