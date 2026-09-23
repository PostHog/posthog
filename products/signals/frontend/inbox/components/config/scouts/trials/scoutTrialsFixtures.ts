import type {
    ScoutTrialResultApi,
    ScoutTrialSetupApi,
    SignalScoutConfigApi,
} from 'products/signals/frontend/generated/api.schemas'

export const trialFixtureConfig: SignalScoutConfigApi = {
    id: '00000000-0000-4000-8000-000000000001',
    skill_name: 'signals-scout-checkout-quality',
    display_name: 'Checkout quality',
    description: 'Find recurring checkout issues in product feedback.',
    deprecation: null,
    scout_origin: 'custom',
    scout_role: 'specialist',
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
    model: 'gpt-5.6-terra',
    last_run_at: null,
    consecutive_failure_count: 0,
    status_changed_at: null,
    status_changed_by: null,
    auto_pause_exempt: false,
    tags: [],
    mcp_gateway_server_ids: [],
    write_scopes: [],
    source_product: null,
    source_id: null,
    created_at: '2026-01-01T09:00:00Z',
    updated_at: '2026-01-01T09:00:00Z',
}

export const trialFixtureSetup: ScoutTrialSetupApi = {
    config_id: trialFixtureConfig.id,
    skill_name: trialFixtureConfig.skill_name,
    skill_version: 3,
    skill_body: 'Review product feedback for recurring checkout failures. Confirm the evidence before filing a report.',
    ready: true,
    blocked_reason: null,
    model: 'gpt-5.6-terra',
    reasoning_effort: 'medium',
    models: [
        { model: 'gpt-5.6-luna', reasoning_efforts: ['low', 'medium', 'high'] },
        { model: 'gpt-5.6-terra', reasoning_efforts: ['low', 'medium', 'high'] },
        { model: 'gpt-5.6-sol', reasoning_efforts: ['low', 'medium', 'high'] },
    ],
}

export const trialFixtureResult: ScoutTrialResultApi = {
    launch_id: '00000000-0000-4000-8000-000000000002',
    context_id: '00000000-0000-4000-8000-000000000003',
    model: 'gpt-5.6-terra',
    reasoning_effort: 'medium',
    skill_body_sha256: 'a'.repeat(64),
    result_key: null,
    export_error: null,
    started_at: '2026-01-01T10:00:00Z',
    completed_at: '2026-01-01T10:04:00Z',
    run_id: '00000000-0000-4000-8000-000000000004',
    task_id: '00000000-0000-4000-8000-000000000005',
    task_run_id: '00000000-0000-4000-8000-000000000006',
    status: 'completed',
    task_status: 'completed',
    error: null,
    summary:
        'Reviewed recent checkout feedback and checked related events. Captured one report with reproducible evidence.',
    invalid_reason: null,
    reports: [
        {
            id: '00000000-0000-4000-8000-000000000007',
            document: {
                title: 'Coupon removal clears the delivery choice',
                content:
                    'Removing a coupon also resets the selected delivery option. Three synthetic feedback events describe the same sequence.\n\nReproduce by selecting express delivery, applying a coupon, and removing it before payment.',
            },
        },
    ],
    memory: {
        'finding:checkout:delivery-reset': {
            key: 'finding:checkout:delivery-reset',
            content: 'Investigated delivery selection reset after coupon removal.',
            created_at: '2026-01-01T10:03:00Z',
            updated_at: '2026-01-01T10:03:00Z',
            created_by_run_id: '00000000-0000-4000-8000-000000000004',
        },
    },
    cost_usd: null,
    input_tokens: 18500,
    output_tokens: 2400,
}
