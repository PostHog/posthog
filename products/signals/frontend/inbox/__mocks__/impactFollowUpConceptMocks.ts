export type FollowUpStage = 'planned' | 'watching' | 'finished'
export type FollowUpVerdict = 'met' | 'failed' | 'inconclusive'

export interface ImpactEvidence {
    signal: string
    baseline: string
    target: string
    watching: string
    finished: string
    result: 'met' | 'failed' | 'missing'
}

export interface ImpactFollowUpExample {
    id: string
    title: string
    goal: string
    primarySignal: string
    baseline: string
    watchingValue: string
    finishedValue: string
    window: string
    watchingProgress: string
    releaseGate: string
    minimumEvidence: string
    query: string
    evidence: ImpactEvidence[]
    verdict: FollowUpVerdict
    reason: string
    nextStep: string
}

// Invented values and illustrative event names. None of these rows are observed production data.
export const impactFollowUpExamples: ImpactFollowUpExample[] = [
    {
        id: 'not-found-pages',
        title: 'False not-found pages',
        goal: 'No false not-found renders on target pages; retry still succeeds.',
        primarySignal: 'False not-found renders',
        baseline: '18 in 3 days',
        watchingValue: '0 in 1 day',
        finishedValue: '0 in 3 days',
        window: '3 days after the web release',
        watchingProgress: 'Day 1 of 3 · 33%',
        releaseGate: 'Web release confirmed; page visits observed',
        minimumEvidence: 'At least 30 target-page views and 5 retries',
        query: `SELECT toDate(timestamp) AS day, countIf(properties.outcome = 'false_not_found') AS false_not_found, countIf(properties.outcome = 'retry_success') AS retry_success, count() AS views\nFROM events WHERE event = 'example_page_result' AND timestamp >= {release_time}\nGROUP BY day ORDER BY day`,
        evidence: [
            { signal: 'False not-found renders', baseline: '18 / 90 views', target: '0, with ≥30 views', watching: '0 / 35', finished: '0 / 110', result: 'met' },
            { signal: 'Successful retries', baseline: '6 / 8', target: '≥5 / 5', watching: '2 / 2', finished: '8 / 8', result: 'met' },
        ],
        verdict: 'met',
        reason: 'Target-page traffic continued, false errors stopped, and retries succeeded. Both checks passed.',
        nextStep: 'Resolve the report and keep the evidence attached.',
    },
    {
        id: 'missing-check-id',
        title: 'Report-check request validation',
        goal: 'No missing identifier rejections once clients have the new tool definition.',
        primarySignal: 'Missing identifier rejections',
        baseline: '7 / 90 calls',
        watchingValue: '2 / 45 calls',
        finishedValue: '4 / 120 calls',
        window: '2 days after client exposure',
        watchingProgress: 'Day 1 of 2 · 50%',
        releaseGate: 'New tool definition available to active clients',
        minimumEvidence: 'At least 100 calls using the new definition',
        query: `SELECT toDate(timestamp) AS day, countIf(properties.error_kind = 'missing_identifier') AS rejected, count() AS calls\nFROM events WHERE event = 'example_report_check_call' AND properties.definition_version = 'new' AND timestamp >= {exposure_time}\nGROUP BY day ORDER BY day`,
        evidence: [
            { signal: 'Missing identifier rejections', baseline: '7 / 90', target: '0 / ≥100 calls', watching: '2 / 45', finished: '4 / 120', result: 'failed' },
            { signal: 'New definition exposure', baseline: 'Not available', target: 'All measured calls', watching: '45 / 45', finished: '120 / 120', result: 'met' },
        ],
        verdict: 'failed',
        reason: 'Rejections remain despite measured calls using the new definition. Some callers may still omit the identifier.',
        nextStep: 'Reopen this report or start a follow-up with the rejected-call examples.',
    },
    {
        id: 'unused-field',
        title: 'Unused confidence field',
        goal: 'Field stays empty on every daily emission for two full weeks.',
        primarySignal: 'Emissions with a value',
        baseline: '0 / 20 emissions',
        watchingValue: '0 / 6 emissions',
        finishedValue: '0 / 10 emissions',
        window: '14 days after release',
        watchingProgress: 'Day 6 of 14 · 43%',
        releaseGate: 'Producer release confirmed',
        minimumEvidence: 'At least one emission on each of 14 days',
        query: `SELECT toDate(timestamp) AS day, count() AS emissions, countIf(properties.confidence_value IS NOT NULL) AS populated\nFROM events WHERE event = 'example_report_emitted' AND timestamp >= {release_time}\nGROUP BY day ORDER BY day`,
        evidence: [
            { signal: 'Emissions with a value', baseline: '0 / 20', target: '0 for 14 days', watching: '0 / 6', finished: '0 / 10', result: 'met' },
            { signal: 'Days with emissions', baseline: '4 / 4', target: '14 / 14', watching: '6 / 6', finished: '10 / 14', result: 'missing' },
        ],
        verdict: 'inconclusive',
        reason: 'The field stayed empty when events arrived, but four days had no emissions. The all-days gate did not pass.',
        nextStep: 'Check producer health; restart the window when daily emissions return.',
    },
    {
        id: 'large-selection',
        title: 'Large scan selections',
        goal: 'A selection over the request limit completes across multiple batches.',
        primarySignal: 'Successful large selections',
        baseline: '0 / 1 selections',
        watchingValue: '0 / 0 selections',
        finishedValue: '0 / 0 selections',
        window: '7 days after release, or 2 large selections',
        watchingProgress: 'Day 3 of 7 · 43%',
        releaseGate: 'Scan client release confirmed',
        minimumEvidence: 'At least 2 selections above the request limit',
        query: `SELECT toDate(timestamp) AS day, countIf(properties.selection_size > 200) AS large_selections, countIf(properties.selection_size > 200 AND properties.completed = true) AS completed\nFROM events WHERE event = 'example_scan_selection_finished' AND timestamp >= {release_time}\nGROUP BY day ORDER BY day`,
        evidence: [
            { signal: 'Large selections completed', baseline: '0 / 1', target: '2 / 2', watching: '0 / 0', finished: '0 / 0', result: 'missing' },
            { signal: 'Qualifying selections', baseline: '1', target: '≥2 after release', watching: '0', finished: '0', result: 'missing' },
        ],
        verdict: 'inconclusive',
        reason: 'No one selected more than the request limit. Per-request batch success cannot prove that a full selection completed.',
        nextStep: 'Extend the window or run a selection-level check with a consenting test project.',
    },
    {
        id: 'webhook-errors',
        title: 'Webhook error handling',
        goal: 'Stop exception captures, preserve 404 responses, and emit one warning per affected response.',
        primarySignal: 'Captured exceptions',
        baseline: '5 in 2 days',
        watchingValue: '0 in 1 day',
        finishedValue: '0 in 2 days',
        window: '2 days after release, with ≥5 affected requests',
        watchingProgress: 'Day 1 of 2 · 50%',
        releaseGate: 'Webhook handler release confirmed',
        minimumEvidence: 'At least 5 affected 404 responses, plus warning telemetry',
        query: `SELECT toDate(timestamp) AS day, countIf(properties.result = 'exception') AS exceptions, countIf(properties.result = 'not_found') AS not_found, countIf(properties.result = 'warning') AS warnings\nFROM events WHERE event = 'example_webhook_result' AND timestamp >= {release_time}\nGROUP BY day ORDER BY day`,
        evidence: [
            { signal: 'Captured exceptions', baseline: '5', target: '0', watching: '0', finished: '0', result: 'met' },
            { signal: '404 responses', baseline: '6', target: '≥5', watching: '3', finished: '7', result: 'met' },
            { signal: 'Warnings for 404s', baseline: 'Not tracked', target: '1 per 404', watching: 'No signal', finished: 'No signal', result: 'missing' },
        ],
        verdict: 'inconclusive',
        reason: 'Exceptions stopped and 404s still appear. Warning telemetry is absent, so the visibility requirement is unverified.',
        nextStep: 'Check the warning destination before declaring success.',
    },
]
