import { emptyResultRule, hasArg } from '../empty-result-rule'
import type { GuidanceCall } from '../engine'
import type { GuidanceRule } from '../rule-schema'

const SESSION_RECORDINGS_LIST_TOOL = 'query-session-recordings-list'

const DIAGNOSIS = [
    'The `posthog:diagnosing-missing-recordings` skill reads them.',
    'Without the skill, query the events with `execute-sql` for `$recording_status`, `$session_recording_start_reason`, `$replay_sample_rate` and `$sdk_debug_recording_script_not_loaded`.',
].join(' ')

function filtersIn(call: GuidanceCall): string[] {
    const testAccounts = call.args?.filter_test_accounts
    return [
        ...(hasArg(call, 'properties') ? ['properties'] : []),
        ...(testAccounts === true || testAccounts === 'true' ? ['filter_test_accounts'] : []),
    ]
}

// The filters come first, because a lookup that also filters can miss a recording that exists.
function lookupIn(call: GuidanceCall): 'no_ids' | 'filters' | 'session_ids' | 'person_uuid' | 'none' {
    const sessionIds = call.args?.session_ids
    if (Array.isArray(sessionIds) && sessionIds.length === 0) {
        return 'no_ids'
    }
    if (filtersIn(call).length > 0) {
        return 'filters'
    }
    return (['session_ids', 'person_uuid'] as const).find((name) => hasArg(call, name)) ?? 'none'
}

function replayRule(rule: {
    id: string
    recordingEnabled: boolean
    matches?: (call: GuidanceCall) => boolean
    requiresTool?: string[]
    text: GuidanceRule['text']
}): GuidanceRule {
    return emptyResultRule({
        id: rule.id,
        tool: SESSION_RECORDINGS_LIST_TOOL,
        requiresTool: [SESSION_RECORDINGS_LIST_TOOL, ...(rule.requiresTool ?? [])],
        when: async ({ call, productState }) =>
            (rule.matches?.(call) ?? true) &&
            (await productState.isSessionRecordingEnabled()) === rule.recordingEnabled,
        text: rule.text,
    })
}

const rules: GuidanceRule[] = [
    replayRule({
        id: 'replay-empty-to-recording-off',
        recordingEnabled: false,
        text: [
            'Session recording is turned off for this project, so PostHog records no new sessions.',
            'Recordings made before it was turned off stay available until they expire.',
            'Do not turn it on unless the user asks for that.',
        ].join(' '),
    }),
    replayRule({
        id: 'replay-empty-to-session-missing',
        recordingEnabled: true,
        matches: (call) => lookupIn(call) === 'session_ids' && hasArg(call, 'date_from'),
        requiresTool: ['execute-sql'],
        text: [
            'None of these session IDs has a recording in this date range.',
            'The events of a session record why it has no recording.',
            DIAGNOSIS,
        ].join(' '),
    }),
    replayRule({
        id: 'replay-empty-to-person',
        recordingEnabled: true,
        matches: (call) => lookupIn(call) === 'person_uuid',
        requiresTool: ['execute-sql'],
        text: [
            'This person has no recording in this date range, and the result covers only this range.',
            'The events of the person record whether each session was recorded, and why not.',
            DIAGNOSIS,
        ].join(' '),
    }),
    replayRule({
        id: 'replay-empty-to-filters',
        recordingEnabled: true,
        matches: (call) => lookupIn(call) === 'filters',
        requiresTool: ['read-data-schema'],
        text: (call) =>
            [
                'Session recording is on for this project, but no recording matched this query in this date range.',
                `This call filtered on ${filtersIn(call)
                    .map((filter) => `\`${filter}\``)
                    .join(' and ')}, so a recording that these filters exclude can still exist.`,
                'A `properties` filter with a wrong property name, value or `type` also matches nothing.',
                '`read-data-schema` lists the property names and values.',
                '`type` is where the property is stored: `person`, `session`, `event` or `recording`.',
            ].join(' '),
    }),
    replayRule({
        id: 'replay-empty-to-range',
        recordingEnabled: true,
        matches: (call) => lookupIn(call) === 'none',
        requiresTool: ['execute-sql'],
        text: [
            'Session recording is on for this project, but this date range has no recordings.',
            'The result covers only this range, and `date_from` defaults to `-3d`.',
            'If recent sessions have no recordings either, their events record why.',
            DIAGNOSIS,
        ].join(' '),
    }),
]

export default rules
