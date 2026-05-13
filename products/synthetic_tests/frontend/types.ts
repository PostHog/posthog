/**
 * Hand-written API types — to be replaced with generated types from `hogli build:openapi`
 * once the serializers land in master. The shapes mirror
 * `products/synthetic_tests/backend/presentation/serializers.py`.
 */

export type SyntheticTestStepType =
    | 'navigate'
    | 'click'
    | 'type'
    | 'wait'
    | 'wait_for_selector'
    | 'assert_element_exists'
    | 'assert_url_contains'
    | 'assert_text_visible'

export interface SyntheticTestStep {
    type: SyntheticTestStepType
    url?: string
    selector?: string
    value?: string
    duration_ms?: number
}

export type SyntheticTestStatus = 'active' | 'paused'

export type SyntheticTestRunStatus = 'running' | 'passed' | 'failed' | 'timeout' | 'error'

export interface SyntheticTestRun {
    id: string
    synthetic_test: string
    started_at: string
    finished_at: string | null
    status: SyntheticTestRunStatus
    duration_ms: number | null
    error_message: string
    error_step_index: number | null
    screenshot_url: string
    issue_id: string | null
}

export interface SyntheticTest {
    id: string
    name: string
    description: string
    target_url: string
    steps: SyntheticTestStep[]
    schedule_cron: string
    timezone: string
    status: SyntheticTestStatus
    create_issue_on_failure: boolean
    source_replay_id: string | null
    created_by: number | null
    created_at: string
    updated_at: string
    next_run_at: string | null
    last_run_at: string | null
    last_run: SyntheticTestRun | null
}

export interface SyntheticTestDraft {
    name: string
    target_url: string
    steps: SyntheticTestStep[]
    schedule_cron: string
    timezone: string
    create_issue_on_failure: boolean
    source_replay_id?: string | null
}

export const SCHEDULE_PRESETS: { label: string; cron: string }[] = [
    { label: 'Every 5 minutes', cron: '*/5 * * * *' },
    { label: 'Every 15 minutes', cron: '*/15 * * * *' },
    { label: 'Every hour', cron: '0 * * * *' },
    { label: 'Every day', cron: '0 0 * * *' },
]

export const STEP_TYPES: { type: SyntheticTestStepType; label: string; description: string }[] = [
    { type: 'navigate', label: 'Navigate', description: 'Go to a URL' },
    { type: 'click', label: 'Click', description: 'Click an element matching a CSS selector' },
    { type: 'type', label: 'Type', description: 'Type a value into an input' },
    { type: 'wait', label: 'Wait', description: 'Pause for N milliseconds' },
    { type: 'wait_for_selector', label: 'Wait for selector', description: 'Wait until an element appears' },
    {
        type: 'assert_element_exists',
        label: 'Assert element exists',
        description: 'Fail if the selector matches zero elements',
    },
    {
        type: 'assert_url_contains',
        label: 'Assert URL contains',
        description: 'Fail unless the URL contains the value',
    },
    {
        type: 'assert_text_visible',
        label: 'Assert text visible',
        description: 'Fail unless the text is visible on the page',
    },
]
