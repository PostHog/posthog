import type {
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
