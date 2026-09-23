/**
 * Withholds everything but the AI payload from `query-llm-trace` and
 * `query-llm-traces-list` responses.
 *
 * An event's `properties` bag is caller-controlled and open-ended. Next to the
 * prompts and costs an agent asks for, it carries whatever the calling
 * application, its framework, and PostHog put there: authentication state,
 * credential and session handles, forwarded request headers, user identity,
 * permission and budget context, and location. A rule that names what to drop
 * always trails the data, so this is an allowlist: a property reaches the client
 * only if it is a known AI taxonomy property or one of a few navigation fields.
 * Anything else is withheld and only its name is reported, so an agent can see
 * that a property exists and read it in PostHog.
 *
 * Redaction is a client-boundary safeguard on these two tools only. Stored
 * events, the PostHog UI, and property filters keep the complete bag, so a query
 * can still filter on a property it cannot read back.
 */

import { assignKey, isRecord } from '@/lib/trace-compaction'

/**
 * Event properties that reach the client. Every `$ai_*` name PostHog's taxonomy
 * defines, so the AI payload of a trace is unchanged. A prefix test would be
 * shorter, but capture does not reserve the `$ai_` namespace: an application
 * that names its own property `$ai_authorization` would hand its value straight
 * back. `trace-redaction-allowlist.test.ts` fails when the taxonomy gains or
 * loses a property, so the list cannot drift silently.
 */
export const RETAINED_AI_PROPERTIES = new Set([
    '$ai_agent_name',
    '$ai_audio_cost_usd',
    '$ai_audio_input_tokens',
    '$ai_audio_output_tokens',
    '$ai_base_url',
    '$ai_billable',
    '$ai_blob_bytes',
    '$ai_blob_count',
    '$ai_cache_creation_1h_input_tokens',
    '$ai_cache_creation_5m_input_tokens',
    '$ai_cache_creation_input_tokens',
    '$ai_cache_read_audio_tokens',
    '$ai_cache_read_input_tokens',
    '$ai_cache_read_token_price',
    '$ai_cache_reporting_exclusive',
    '$ai_cache_write_1h_token_price',
    '$ai_cache_write_token_price',
    '$ai_cost_model_provider',
    '$ai_cost_model_source',
    '$ai_cost_passthrough',
    '$ai_error',
    '$ai_error_normalized',
    '$ai_error_type',
    '$ai_eval_source',
    '$ai_evaluation_allows_na',
    '$ai_evaluation_applicable',
    '$ai_evaluation_id',
    '$ai_evaluation_key_id',
    '$ai_evaluation_key_type',
    '$ai_evaluation_model',
    '$ai_evaluation_name',
    '$ai_evaluation_provider',
    '$ai_evaluation_reasoning',
    '$ai_evaluation_result',
    '$ai_evaluation_runtime',
    '$ai_evaluation_start_time',
    '$ai_evaluation_type',
    '$ai_expected',
    '$ai_experiment_id',
    '$ai_experiment_item_id',
    '$ai_experiment_item_name',
    '$ai_experiment_name',
    '$ai_feedback_text',
    '$ai_framework',
    '$ai_git_branch',
    '$ai_git_repo',
    '$ai_http_status',
    '$ai_image_cost_usd',
    '$ai_image_input_tokens',
    '$ai_image_output_tokens',
    '$ai_ingestion_source',
    '$ai_input',
    '$ai_input_cost_usd',
    '$ai_input_state',
    '$ai_input_token_price',
    '$ai_input_tokens',
    '$ai_is_error',
    '$ai_latency',
    '$ai_lib',
    '$ai_lib_version',
    '$ai_max_tokens',
    '$ai_metric_name',
    '$ai_metric_value',
    '$ai_metric_version',
    '$ai_model',
    '$ai_model_cost_used',
    '$ai_model_parameters',
    '$ai_output',
    '$ai_output_choices',
    '$ai_output_cost_usd',
    '$ai_output_state',
    '$ai_output_token_price',
    '$ai_output_tokens',
    '$ai_parent_id',
    '$ai_project_name',
    '$ai_prompt_name',
    '$ai_prompt_version',
    '$ai_prompt_version_id',
    '$ai_provider',
    '$ai_reasoning',
    '$ai_reasoning_tokens',
    '$ai_request_cost_usd',
    '$ai_request_count',
    '$ai_request_price',
    '$ai_request_url',
    '$ai_result_type',
    '$ai_score',
    '$ai_score_max',
    '$ai_score_min',
    '$ai_session_id',
    '$ai_span_id',
    '$ai_span_name',
    '$ai_span_type',
    '$ai_status',
    '$ai_stop_reason',
    '$ai_stream',
    '$ai_tag_count',
    '$ai_tag_reasoning',
    '$ai_tagger_id',
    '$ai_tagger_key_id',
    '$ai_tagger_key_type',
    '$ai_tagger_name',
    '$ai_tagger_start_time',
    '$ai_tags',
    '$ai_target_event_id',
    '$ai_target_event_type',
    '$ai_target_id',
    '$ai_target_type',
    '$ai_temperature',
    '$ai_text_input_tokens',
    '$ai_text_output_tokens',
    '$ai_time_to_first_token',
    '$ai_tokens_source',
    '$ai_tool_call_count',
    '$ai_tools',
    '$ai_tools_called',
    '$ai_total_cost_usd',
    '$ai_total_input_tokens',
    '$ai_total_output_tokens',
    '$ai_total_tokens',
    '$ai_trace_id',
    '$ai_trace_name',
    '$ai_user_prompt',
    '$ai_video_cost_usd',
    '$ai_video_input_tokens',
    '$ai_video_output_tokens',
    '$ai_web_search_cost_usd',
    '$ai_web_search_count',
    '$ai_web_search_price',
])

/** Non-`$ai_*` properties kept so a trace stays navigable and attributable. */
export const RETAINED_NAVIGATION_PROPERTIES = new Set(['$session_id', '$lib', '$lib_version'])

/**
 * Endpoint properties kept without their query string. A provider URL routinely
 * carries the API key as a query parameter.
 */
const SANITIZED_URL_PROPERTIES = new Set(['$ai_base_url', '$ai_request_url'])

/** Names of the properties withheld from a bag, reported in place of their values. */
export const REDACTED_KEYS_FIELD = '_redactedKeys'

function sanitizeUrl(value: unknown): unknown {
    if (typeof value !== 'string') {
        return value
    }
    try {
        const url = new URL(value)
        return `${url.origin}${url.pathname}`
    } catch {
        // Not absolute, so `URL` cannot split it. Cut at the first query or
        // fragment marker, which is where a credential would sit.
        return value.split(/[?#]/)[0] ?? value
    }
}

function isRetained(key: string): boolean {
    return RETAINED_AI_PROPERTIES.has(key) || RETAINED_NAVIGATION_PROPERTIES.has(key)
}

function redactProperties(properties: Record<string, unknown>): Record<string, unknown> {
    const out: Record<string, unknown> = {}
    const withheld: string[] = []
    for (const [key, value] of Object.entries(properties)) {
        if (SANITIZED_URL_PROPERTIES.has(key)) {
            assignKey(out, key, sanitizeUrl(value))
        } else if (isRetained(key)) {
            assignKey(out, key, value)
        } else {
            withheld.push(key)
        }
    }
    if (withheld.length > 0) {
        assignKey(out, REDACTED_KEYS_FIELD, withheld)
    }
    return out
}

function redactBagOn(owner: Record<string, unknown>): Record<string, unknown> {
    const properties = owner.properties
    if (!isRecord(properties)) {
        return owner
    }
    return { ...owner, properties: redactProperties(properties) }
}

/** Redact one trace: every event bag, and the person bag attached to the trace. */
export function redactTrace(trace: unknown): unknown {
    if (!isRecord(trace)) {
        return trace
    }
    const out: Record<string, unknown> = { ...trace }
    if (Array.isArray(trace.events)) {
        out.events = trace.events.map((event) => (isRecord(event) ? redactBagOn(event) : event))
    }
    if (isRecord(trace.person)) {
        out.person = redactBagOn(trace.person)
    }
    return out
}

/** Redact the `results` array of a trace query, before it is compacted. */
export function redactTraceResults(results: unknown): unknown {
    return Array.isArray(results) ? results.map(redactTrace) : results
}
