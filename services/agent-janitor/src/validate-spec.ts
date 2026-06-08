/**
 * Pre-flight validation for a draft / ready revision.
 *
 * Catches the shape problems that would otherwise surface as a session-start
 * crash on first invoke: missing entrypoint, unknown native tool ids, custom
 * tools without a compiled.js, skills that point at files that aren't in the
 * bundle.
 *
 * Spec parsing itself is guaranteed by the revision store (PgRevisionStore
 * runs `AgentSpecSchema.parse(row.spec ?? {})` on every read), so we don't
 * re-validate the spec shape here.
 *
 * Secrets validation lives in Django — it owns the encrypted env block and
 * the Fernet keys. The janitor only validates bundle-side things.
 */

import cronParser from 'cron-parser'

import { AgentRevision, BundleStore } from '@posthog/agent-shared'
import { hasNativeTool } from '@posthog/agent-tools'

export type ValidationCode =
    | 'no_triggers'
    | 'missing_entrypoint'
    | 'unknown_native_tool'
    | 'invalid_cron_schedule'
    | 'cron_schedule_too_frequent'
    | 'invalid_cron_timezone'
    | 'duplicate_cron_name'
    | 'unknown_cron_placeholder'

/**
 * Non-blocking soft signals — surface to the author before freeze, but the
 * runner will still load the revision. Kept as a typed union for future
 * use; the orphan_skill/tool warnings became structurally impossible once
 * the typed authoring API landed and spec.skills/tools are server-derived.
 */
export type ValidationWarningCode = never

/**
 * Placeholder set authors can use inside `external_key` and `prompt` on a
 * cron trigger. Shared between freeze-time validation (here) and runtime
 * expansion (PR-3 of `cron-trigger-scheduler.md`). Anything outside this
 * set is rejected at freeze rather than letting an unrecognized `{foo}`
 * silently pass through to the firing message.
 */
export const CRON_PLACEHOLDERS: ReadonlySet<string> = new Set([
    'fired_at:iso',
    'fired_at:date',
    'fired_at:week',
    'schedule',
    'cron_name',
])

/**
 * Minimum interval between two consecutive cron firings. The janitor ticks on
 * a ~30s loop and catch-up fires per surviving firing — a sub-minute (6-field)
 * schedule like `* * * * * *` turns a paused janitor + the 7-day catch-up cap
 * into a fire storm of hundreds of thousands of sessions in one tick. Reject
 * those at freeze; the per-tick cap in `cron-tick.ts` is the runtime backstop.
 */
const MIN_CRON_INTERVAL_SECONDS = 60

export interface ValidationError {
    code: ValidationCode
    message: string
    /** Spec path the error attaches to (e.g. "spec.tools[2].id", "spec.entrypoint"). */
    pointer: string
}

export interface ValidationWarning {
    code: ValidationWarningCode
    message: string
    /** Bundle path the warning attaches to (e.g. "tools/incidentio-list-schedules/"). */
    pointer: string
}

export interface ValidationReport {
    ok: boolean
    revision_id: string
    revision_state: AgentRevision['state']
    errors: ValidationError[]
    /**
     * Soft signals — the author probably wants to act on these before
     * freezing, but the runner won't reject the revision. Currently:
     *   - `orphan_custom_tool_dir`: a `tools/<id>/schema.json` exists in
     *     the bundle but no `spec.tools[]` entry references it. Catches
     *     the "wrote the tool source but forgot to add the spec ref"
     *     bug that's the most common authoring foot-gun, especially
     *     for AI authors.
     *   - `orphan_skill_file`: a `skills/.../SKILL.md` exists in the
     *     bundle but no `spec.skills[]` entry references it. Same shape.
     */
    warnings: ValidationWarning[]
    /** Native tool ids referenced by the spec that resolved fine. */
    resolved_natives: string[]
}

export async function validateRevisionBundle(rev: AgentRevision, bundle: BundleStore): Promise<ValidationReport> {
    const errors: ValidationError[] = []
    const warnings: ValidationWarning[] = []
    const resolvedNatives: string[] = []

    // An agent with no triggers has no surface to be invoked through — every
    // /run / /webhook / cron tick would 404 with `no_*_trigger`. Treat as a
    // hard error at freeze so we can't promote a dead-on-arrival revision.
    if (rev.spec.triggers.length === 0) {
        errors.push({
            code: 'no_triggers',
            message: 'spec.triggers is empty; the agent has no entry points and cannot be invoked',
            pointer: 'spec.triggers',
        })
    }

    const entrypoint = rev.spec.entrypoint || 'agent.md'
    if (!(await bundle.exists(rev.id, entrypoint))) {
        errors.push({
            code: 'missing_entrypoint',
            message: `entrypoint "${entrypoint}" is not present in the bundle`,
            pointer: 'spec.entrypoint',
        })
    }

    // Tool / skill bundle-presence checks used to live here (orphan
    // detection, missing source / schema). With the typed authoring API
    // (`docs/agent-platform/plans/typed-bundle-authoring-api.md`) those
    // failures are structurally impossible: `spec.tools[]` /
    // `spec.skills[]` are server-derived at freeze from the actual typed
    // resources in the bundle, so a missing-file failure means the freeze
    // never derived the entry in the first place. The native-tool
    // registry check below is still real (an unregistered `@posthog/X`
    // can land in spec via the author-facing `PUT /spec`).
    for (const [i, tool] of rev.spec.tools.entries()) {
        if (tool.kind === 'native') {
            if (!hasNativeTool(tool.id)) {
                errors.push({
                    code: 'unknown_native_tool',
                    message: `native tool "${tool.id}" is not registered in @posthog/agent-tools`,
                    pointer: `spec.tools[${i}].id`,
                })
            } else {
                resolvedNatives.push(tool.id)
            }
        }
        // kind:'custom' / kind:'client' need no presence check — see above.
    }

    // Cron-specific freeze-time checks. Zod has already validated the field
    // shapes (`name` regex, `prompt` length, `max_catch_up_age_seconds`
    // bounds, etc.) — these are the cross-cutting / runtime checks zod can't
    // express: schedule parses against cron-parser, timezone resolves to a
    // real IANA zone, names are unique across triggers, placeholders are
    // whitelisted.
    const cronNamesSeen = new Set<string>()
    for (const [i, trigger] of rev.spec.triggers.entries()) {
        if (trigger.type !== 'cron') {
            continue
        }
        const cfg = trigger.config
        try {
            const it = cronParser.parseExpression(cfg.schedule, { tz: cfg.timezone })
            // Reject schedules that fire more than once a minute. We can only
            // measure the gap when two firings exist; a one-shot schedule
            // (no second firing) is harmless and slips through unflagged.
            try {
                const first = it.next().toDate().getTime()
                const second = it.next().toDate().getTime()
                if (second - first < MIN_CRON_INTERVAL_SECONDS * 1000) {
                    errors.push({
                        code: 'cron_schedule_too_frequent',
                        message: `cron "${cfg.name}" schedule "${cfg.schedule}" fires more than once a minute; the minimum interval is ${MIN_CRON_INTERVAL_SECONDS}s`,
                        pointer: `spec.triggers[${i}].config.schedule`,
                    })
                }
            } catch {
                // No second firing to compare against — not a frequency risk.
            }
        } catch (err) {
            errors.push({
                code: 'invalid_cron_schedule',
                message: `cron "${cfg.name}" schedule "${cfg.schedule}" is not a valid cron expression: ${(err as Error).message}`,
                pointer: `spec.triggers[${i}].config.schedule`,
            })
        }
        if (!isValidTimezone(cfg.timezone)) {
            errors.push({
                code: 'invalid_cron_timezone',
                message: `cron "${cfg.name}" timezone "${cfg.timezone}" is not a recognised IANA zone`,
                pointer: `spec.triggers[${i}].config.timezone`,
            })
        }
        if (cronNamesSeen.has(cfg.name)) {
            errors.push({
                code: 'duplicate_cron_name',
                message: `cron name "${cfg.name}" appears on more than one trigger; names must be unique within spec.triggers[]`,
                pointer: `spec.triggers[${i}].config.name`,
            })
        }
        cronNamesSeen.add(cfg.name)
        for (const placeholder of unknownPlaceholders(cfg.prompt)) {
            errors.push({
                code: 'unknown_cron_placeholder',
                message: `cron "${cfg.name}" prompt references unknown placeholder "{${placeholder}}"; allowed: ${[...CRON_PLACEHOLDERS].join(', ')}`,
                pointer: `spec.triggers[${i}].config.prompt`,
            })
        }
        if (cfg.external_key) {
            for (const placeholder of unknownPlaceholders(cfg.external_key)) {
                errors.push({
                    code: 'unknown_cron_placeholder',
                    message: `cron "${cfg.name}" external_key references unknown placeholder "{${placeholder}}"; allowed: ${[...CRON_PLACEHOLDERS].join(', ')}`,
                    pointer: `spec.triggers[${i}].config.external_key`,
                })
            }
        }
    }

    return {
        ok: errors.length === 0,
        revision_id: rev.id,
        revision_state: rev.state,
        errors,
        warnings,
        resolved_natives: resolvedNatives,
    }
}

/**
 * `Intl.DateTimeFormat` is the most reliable IANA-zone validator that ships
 * with the Node runtime — it throws on unknown zones and accepts the same
 * set `cron-parser` does (both delegate to ICU).
 */
function isValidTimezone(tz: string): boolean {
    try {
        new Intl.DateTimeFormat('en', { timeZone: tz })
        return true
    } catch {
        return false
    }
}

/**
 * Yield every `{placeholder}` token in `input` that isn't in
 * `CRON_PLACEHOLDERS`. Matches conservatively — single-line, no escapes —
 * the same conservative shape the runtime expander uses, so what passes
 * validation is exactly what the firing path can resolve.
 */
function unknownPlaceholders(input: string): string[] {
    const out: string[] = []
    const re = /\{([^{}\s]+)\}/g
    let match: RegExpExecArray | null
    while ((match = re.exec(input)) !== null) {
        if (!CRON_PLACEHOLDERS.has(match[1])) {
            out.push(match[1])
        }
    }
    return out
}
