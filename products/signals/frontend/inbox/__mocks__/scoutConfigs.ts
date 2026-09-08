import type {
    ScoutSuggestionItemApi,
    ScoutSuggestionSetApi,
    SignalScoutConfigApi,
    SignalScoutRunSummaryApi,
    UserBasicApi,
} from 'products/signals/frontend/generated/api.schemas'

type MockScoutOverrides = Pick<SignalScoutConfigApi, 'id' | 'skill_name' | 'description'> &
    Partial<Omit<SignalScoutConfigApi, 'id' | 'skill_name' | 'description'>>

function makeMockOwner(id: number, firstName: string, lastName: string): UserBasicApi {
    return {
        id,
        uuid: `0000000${id}-0000-0000-0000-000000000000`,
        distinct_id: `owner-${id}`,
        first_name: firstName,
        last_name: lastName,
        email: `${firstName.toLowerCase()}@example.com`,
        is_email_verified: true,
        hedgehog_config: null,
    }
}

const MOCK_SCOUT_OWNERS = [
    makeMockOwner(1, 'Ada', 'Ellis'),
    makeMockOwner(2, 'Bo', 'Nakamura'),
    makeMockOwner(3, 'Cleo', 'Farah'),
    makeMockOwner(4, 'Devi', 'Osei'),
]

function makeMockScout(overrides: MockScoutOverrides): SignalScoutConfigApi {
    return {
        scout_origin: 'canonical',
        owners: [],
        enabled: true,
        status: 'active',
        pause_reason: null,
        emit: true,
        run_interval_minutes: 1440,
        run_cron_schedule: null,
        output_destinations: {},
        structured_output_schema: null,
        network_access: 'trusted',
        model: null,
        last_run_at: null,
        consecutive_failure_count: 0,
        status_changed_at: null,
        auto_pause_exempt: false,
        tags: [],
        mcp_gateway_server_ids: [],
        write_scopes: [],
        source_product: null,
        source_id: null,
        created_at: '2026-06-11T09:00:00Z',
        ...overrides,
    }
}

export const mockScoutConfigs: SignalScoutConfigApi[] = [
    makeMockScout({
        id: 'scout-error-tracking',
        skill_name: 'signals-scout-error-tracking',
        description: 'new errors, regressions, and spikes in Error tracking',
        run_interval_minutes: 60,
        last_run_at: '2026-06-10T23:30:00Z',
        write_scopes: ['dashboard:write'],
    }),
    makeMockScout({
        id: 'scout-session-replay',
        skill_name: 'signals-scout-session-replay',
        description: 'session recordings for repeated usability problems',
        last_run_at: '2026-06-10T12:00:00Z',
    }),
]

/** Anchors the mock runs to the same instant the scout stories pin `mockDate` to. */
const MOCK_NOW_MS = Date.parse('2026-06-11T09:00:00Z')
const HOUR_MS = 3600000

/**
 * A run strip for every scout in a fleet: hourly runs ending at the stories' "now", with a
 * repeating emitted / quiet / failed pattern so the strip shows all three box colors. Scouts get
 * different run counts on purpose — that's what the right-anchored strip exists to keep comparable.
 */
export function mockScoutRuns(configs: SignalScoutConfigApi[]): SignalScoutRunSummaryApi[] {
    return configs.flatMap((config, configIndex) =>
        Array.from({ length: 10 + configIndex * 2 }, (_, runIndex) => {
            const failed = (runIndex + configIndex) % 5 === 0
            const startedAt = MOCK_NOW_MS - (runIndex + 1) * HOUR_MS
            return {
                run_id: `${config.skill_name}-run-${runIndex}`,
                skill_name: config.skill_name,
                skill_version: 1,
                status: failed ? ('failed' as const) : ('completed' as const),
                created_at: new Date(startedAt).toISOString(),
                started_at: new Date(startedAt).toISOString(),
                completed_at: new Date(startedAt + 12 * 60000).toISOString(),
                task_url: null,
                summary: failed ? '' : 'Swept the window and found nothing worth filing.',
                emitted_count: !failed && (runIndex + configIndex) % 4 === 0 ? 1 : 0,
                emitted_finding_ids: [],
                emitted_report_ids: [],
                edited_report_ids: [],
                metadata: {},
            }
        })
    )
}

export const mockLargeScoutFleet: SignalScoutConfigApi[] = [
    makeMockScout({
        id: 'scout-error-tracking',
        skill_name: 'signals-scout-error-tracking',
        description: 'new errors, regressions, and spikes in Error tracking',
        run_interval_minutes: 60,
        last_run_at: '2026-06-10T23:30:00Z',
        write_scopes: ['dashboard:write'],
    }),
    makeMockScout({
        id: 'scout-checkout-health',
        skill_name: 'signals-scout-checkout-health',
        description: 'checkout failures and unusual drops in completed purchases',
        scout_origin: 'custom',
        owners: [MOCK_SCOUT_OWNERS[0]],
        run_interval_minutes: 30,
        last_run_at: '2026-06-10T23:50:00Z',
        tags: ['checkout', 'revenue'],
    }),
    makeMockScout({
        id: 'scout-product-analytics',
        skill_name: 'signals-scout-product-analytics',
        description: 'unexpected changes in activation, retention, and conversion',
        run_cron_schedule: '0 9 * * *',
    }),
    makeMockScout({
        id: 'scout-session-replay',
        skill_name: 'signals-scout-session-replay',
        description: 'session recordings for repeated usability problems',
        run_interval_minutes: 720,
        last_run_at: '2026-06-10T18:00:00Z',
    }),
    makeMockScout({
        id: 'scout-enterprise-adoption',
        skill_name: 'signals-scout-enterprise-adoption',
        description: 'changes in feature adoption across enterprise accounts',
        scout_origin: 'custom',
        owners: MOCK_SCOUT_OWNERS,
        run_cron_schedule: '30 8 * * 1',
        tags: ['adoption'],
    }),
    makeMockScout({
        id: 'scout-api-latency',
        skill_name: 'signals-scout-api-latency',
        description: 'slow API endpoints and changes in response time',
        scout_origin: 'custom',
        run_interval_minutes: 120,
        last_run_at: '2026-06-10T23:00:00Z',
    }),
    makeMockScout({
        id: 'scout-paused',
        skill_name: 'signals-scout-data-warehouse',
        description: 'failed and delayed data warehouse syncs',
        enabled: false,
        status: 'paused_by_user',
    }),
    makeMockScout({
        id: 'scout-dry-run',
        skill_name: 'signals-scout-experiments',
        description: 'experiments with unexpected or inconclusive results',
        emit: false,
    }),
    makeMockScout({
        id: 'scout-broken',
        skill_name: 'signals-scout-logs',
        description: 'error spikes and new failure patterns in application logs',
        enabled: false,
        status: 'paused_by_system',
        pause_reason: 'repeated_failures',
        consecutive_failure_count: 3,
        status_changed_at: '2026-06-10T08:00:00Z',
    }),
    makeMockScout({
        id: 'scout-warned',
        skill_name: 'signals-scout-surveys',
        description: 'survey responses that point at a product problem',
        status: 'pending_pause',
        pause_reason: 'ignored',
    }),
]

function makeMockSuggestion(
    overrides: Partial<ScoutSuggestionItemApi> & Pick<ScoutSuggestionItemApi, 'id'>
): ScoutSuggestionItemApi {
    return {
        kind: 'canonical' as const,
        skill_name: 'signals-scout-web-vitals',
        title: 'Watch web vitals on the pricing page',
        why_here: 'Pricing has the slowest LCP of any page here, and it moved twice in the last month.',
        description: '',
        draft_body: '',
        proposed_config: { run_cron_schedule: null, run_interval_minutes: 1440, emit: true },
        gap: false,
        confidence: 'medium' as const,
        ...overrides,
    }
}

export const mockScoutSuggestions: ScoutSuggestionItemApi[] = [
    makeMockSuggestion({ id: 'suggestion-web-vitals', gap: true, confidence: 'high' }),
    makeMockSuggestion({
        id: 'suggestion-signup-drop-off',
        kind: 'custom',
        skill_name: 'signals-scout-signup-drop-off',
        title: 'Watch signup drop-off by plan',
        why_here: 'Signups on the team plan convert half as often as on the free plan, and nothing watches it.',
        description: 'Investigates sudden drops in completed signups, split by plan.',
        draft_body:
            'Every run, compare completed signups against started signups for the last 24 hours, split by plan.\n\nFile a report when any plan drops more than 20% against its trailing two-week average. Ignore plans with fewer than 20 starts in the window.',
        proposed_config: { run_cron_schedule: '30 9 * * 1-5', run_interval_minutes: null, emit: true },
        confidence: 'high',
    }),
    makeMockSuggestion({
        id: 'suggestion-warehouse-freshness',
        kind: 'custom',
        skill_name: 'signals-scout-warehouse-freshness',
        title: 'Watch warehouse sync freshness',
        why_here: 'Two of the five sources here have gone a day stale at least once in the last month.',
        description: 'Checks whether every connected warehouse source synced on schedule.',
        draft_body: 'Every run, list the connected sources and their last successful sync.',
        proposed_config: { run_cron_schedule: null, run_interval_minutes: 720, emit: false },
        gap: true,
        confidence: 'low',
    }),
]

export function mockScoutSuggestionSet(overrides: Partial<ScoutSuggestionSetApi> = {}): ScoutSuggestionSetApi {
    return {
        status: 'fresh',
        generated_at: '2026-06-10T09:00:00Z',
        model: '',
        fleet_snapshot: mockScoutConfigs.map((config) => config.skill_name),
        items: mockScoutSuggestions,
        ...overrides,
    }
}
