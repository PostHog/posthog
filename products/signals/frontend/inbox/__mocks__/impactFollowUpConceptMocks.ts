export type FollowUpStage = 'planned' | 'watching' | 'finished'
export type FollowUpVerdict = 'met' | 'failed' | 'inconclusive'

export interface ImpactEvidence {
    signal: string
    baseline: string
    target: string
    watching: string
    finished: string
    result: 'met' | 'failed' | 'missing'
    watchingResult: 'met' | 'failed' | 'waiting' | 'missing'
}

export interface ImpactFollowUpExample {
    id: string
    title: string
    outcome: string
    goal: string
    goalShort: string
    watchingNote: string
    resultNote: string
    primarySignal: string
    baseline: string
    watchingValue: string
    finishedValue: string
    window: string
    watchingProgress: string
    windowDays: number
    elapsedDays: number
    decisionDate: string
    sampleLabel: string
    sampleNeeded: number
    watchingSample: number
    finishedSample: number
    chartLabel: string
    beforeTrend: number[]
    afterTrend: number[]
    chartGoal: number | null
    chartGoalLabel: string
    releaseGate: string
    minimumEvidence: string
    query: string
    evidence: ImpactEvidence[]
    verdict: FollowUpVerdict
    watchingSignal: 'promising' | 'risk' | 'no_trial' | 'missing_signal'
    reason: string
    nextStep: string
}

// Invented values and illustrative event names. None of these rows are observed production data.
export const impactFollowUpExamples: ImpactFollowUpExample[] = [
    {
        id: 'not-found-pages',
        title: 'False not-found pages',
        outcome: 'Restore access to these pages',
        goal: 'No false not-found renders on target pages; retry still succeeds.',
        goalShort: '0 false errors · retries still work',
        watchingNote: 'The errors have stopped so far. Keep watching for two more days.',
        resultNote: 'The pages load and retries work. The report can close.',
        primarySignal: 'False not-found renders',
        baseline: '18 in 3 days',
        watchingValue: '0 in 1 day',
        finishedValue: '0 in 3 days',
        window: '3 days after the web release',
        watchingProgress: 'Day 1 of 3 · 33%',
        windowDays: 3,
        elapsedDays: 1,
        decisionDate: 'Sep 26',
        sampleLabel: 'Successful retries',
        sampleNeeded: 5,
        watchingSample: 2,
        finishedSample: 8,
        chartLabel: 'False errors each day',
        beforeTrend: [6, 7, 5],
        afterTrend: [0, 0, 0],
        chartGoal: 0,
        chartGoalLabel: '0 errors',
        releaseGate: 'Web release confirmed; page visits observed',
        minimumEvidence: 'At least 30 target-page views and 5 retries',
        query: `SELECT toDate(timestamp) AS day, countIf(properties.outcome = 'false_not_found') AS false_not_found, countIf(properties.outcome = 'retry_success') AS retry_success, count() AS views\nFROM events WHERE event = 'example_page_result' AND timestamp >= {release_time}\nGROUP BY day ORDER BY day`,
        evidence: [
            { signal: 'False not-found renders', baseline: '18 / 90 views', target: '0, with ≥30 views', watching: '0 / 35', finished: '0 / 110', result: 'met', watchingResult: 'met' },
            { signal: 'Successful retries', baseline: '6 / 8', target: '≥5 / 5', watching: '2 / 2', finished: '8 / 8', result: 'met', watchingResult: 'waiting' },
        ],
        watchingSignal: 'promising',
        verdict: 'met',
        reason: 'Target-page traffic continued, false errors stopped, and retries succeeded. Both checks passed.',
        nextStep: 'Resolve the report and keep the evidence attached.',
    },
    {
        id: 'missing-check-id',
        title: 'Report-check request validation',
        outcome: 'Get report checks through without rejections',
        goal: 'No missing identifier rejections once clients have the new tool definition.',
        goalShort: '0 rejected calls · at least 100 new-client calls',
        watchingNote: 'Some calls still fail. Wait for enough calls before deciding.',
        resultNote: 'Calls still fail after the update. Start a new report with these examples.',
        primarySignal: 'Missing identifier rejections',
        baseline: '7 / 90 calls',
        watchingValue: '2 / 45 calls',
        finishedValue: '4 / 120 calls',
        window: '2 days after client exposure',
        watchingProgress: 'Day 1 of 2 · 50%',
        windowDays: 2,
        elapsedDays: 1,
        decisionDate: 'Sep 25',
        sampleLabel: 'Calls after update',
        sampleNeeded: 100,
        watchingSample: 45,
        finishedSample: 120,
        chartLabel: 'Rejected calls each day',
        beforeTrend: [3, 2, 2],
        afterTrend: [2, 2],
        chartGoal: 0,
        chartGoalLabel: '0 rejected',
        releaseGate: 'New tool definition available to active clients',
        minimumEvidence: 'At least 100 calls using the new definition',
        query: `SELECT toDate(timestamp) AS day, countIf(properties.error_kind = 'missing_identifier') AS rejected, count() AS calls\nFROM events WHERE event = 'example_report_check_call' AND properties.definition_version = 'new' AND timestamp >= {exposure_time}\nGROUP BY day ORDER BY day`,
        evidence: [
            { signal: 'Missing identifier rejections', baseline: '7 / 90', target: '0 / ≥100 calls', watching: '2 / 45', finished: '4 / 120', result: 'failed', watchingResult: 'failed' },
            { signal: 'New definition exposure', baseline: 'Not available', target: 'All measured calls', watching: '45 / 45', finished: '120 / 120', result: 'met', watchingResult: 'met' },
        ],
        watchingSignal: 'risk',
        verdict: 'failed',
        reason: 'Rejections remain despite measured calls using the new definition. Some callers may still omit the identifier.',
        nextStep: 'Start a new report with the rejected-call examples.',
    },
    {
        id: 'unused-field',
        title: 'Unused confidence field',
        outcome: 'Know when the old field is safe to remove',
        goal: 'Field stays empty on every daily emission for two full weeks.',
        goalShort: '0 values · data on all 14 days',
        watchingNote: 'No values so far. Daily data must continue for two weeks.',
        resultNote: 'Four days have no data. We cannot prove the field stayed unused.',
        primarySignal: 'Emissions with a value',
        baseline: '0 / 20 emissions',
        watchingValue: '0 / 6 with values',
        finishedValue: '0 / 10 with values',
        window: '14 days after release',
        watchingProgress: 'Day 6 of 14 · 43%',
        windowDays: 14,
        elapsedDays: 6,
        decisionDate: 'Oct 7',
        sampleLabel: 'Days with data',
        sampleNeeded: 14,
        watchingSample: 6,
        finishedSample: 10,
        chartLabel: 'Days with emissions',
        beforeTrend: [1, 1, 1],
        afterTrend: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, NaN, NaN, NaN, NaN],
        chartGoal: 1,
        chartGoalLabel: 'Data each day',
        releaseGate: 'Producer release confirmed',
        minimumEvidence: 'At least one emission on each of 14 days',
        query: `SELECT toDate(timestamp) AS day, count() AS emissions, countIf(properties.confidence_value IS NOT NULL) AS populated\nFROM events WHERE event = 'example_report_emitted' AND timestamp >= {release_time}\nGROUP BY day ORDER BY day`,
        evidence: [
            { signal: 'Emissions with a value', baseline: '0 / 20', target: '0 for 14 days', watching: '0 / 6', finished: '0 / 10', result: 'met', watchingResult: 'met' },
            { signal: 'Days with emissions', baseline: '4 / 4', target: '14 / 14', watching: '6 / 6', finished: '10 / 14', result: 'missing', watchingResult: 'waiting' },
        ],
        watchingSignal: 'promising',
        verdict: 'inconclusive',
        reason: 'The field stayed empty when events arrived, but four days had no emissions. The all-days gate did not pass.',
        nextStep: 'Check producer health; restart the window when daily emissions return.',
    },
    {
        id: 'large-selection',
        title: 'Large scan selections',
        outcome: 'Make large scans finish across batches',
        goal: 'A selection over the request limit completes across multiple batches.',
        goalShort: '2 large selections complete',
        watchingNote: 'Nobody has tried a large selection yet. There is nothing to judge.',
        resultNote: 'Nobody tried a large selection. The fix may work, but we cannot tell.',
        primarySignal: 'Successful large selections',
        baseline: '0 / 1 selections',
        watchingValue: '0 / 0 selections',
        finishedValue: '0 / 0 selections',
        window: '7 days after release, or 2 large selections',
        watchingProgress: 'Day 3 of 7 · 43%',
        windowDays: 7,
        elapsedDays: 3,
        decisionDate: 'Sep 30',
        sampleLabel: 'Large selections seen',
        sampleNeeded: 2,
        watchingSample: 0,
        finishedSample: 0,
        chartLabel: 'Large selections each day',
        beforeTrend: [1, 0, 0],
        afterTrend: [0, 0, 0, 0, 0, 0, 0],
        chartGoal: null,
        chartGoalLabel: 'Need 2 selections in all',
        releaseGate: 'Scan client release confirmed',
        minimumEvidence: 'At least 2 selections above the request limit',
        query: `SELECT toDate(timestamp) AS day, countIf(properties.selection_size > 200) AS large_selections, countIf(properties.selection_size > 200 AND properties.completed = true) AS completed\nFROM events WHERE event = 'example_scan_selection_finished' AND timestamp >= {release_time}\nGROUP BY day ORDER BY day`,
        evidence: [
            { signal: 'Large selections completed', baseline: '0 / 1', target: '2 / 2', watching: '0 / 0', finished: '0 / 0', result: 'missing', watchingResult: 'missing' },
            { signal: 'Qualifying selections', baseline: '1', target: '≥2 after release', watching: '0', finished: '0', result: 'missing', watchingResult: 'missing' },
        ],
        watchingSignal: 'no_trial',
        verdict: 'inconclusive',
        reason: 'No one selected more than the request limit. Per-request batch success cannot prove that a full selection completed.',
        nextStep: 'Extend the window or run a selection-level check with a consenting test project.',
    },
    {
        id: 'webhook-errors',
        title: 'Webhook error handling',
        outcome: 'Keep webhook errors visible without noisy exceptions',
        goal: 'Stop exception captures, preserve 404 responses, and emit one warning per affected response.',
        goalShort: '0 exceptions · keep 404s and warnings',
        watchingNote: 'Exceptions stopped. We still need to see the warning.',
        resultNote: 'Exceptions stopped, but warning data is missing. We cannot confirm visibility.',
        primarySignal: 'Captured exceptions',
        baseline: '5 in 2 days',
        watchingValue: '0 in 1 day',
        finishedValue: '0 in 2 days',
        window: '2 days after release, with ≥5 affected requests',
        watchingProgress: 'Day 1 of 2 · 50%',
        windowDays: 2,
        elapsedDays: 1,
        decisionDate: 'Sep 25',
        sampleLabel: 'Affected requests',
        sampleNeeded: 5,
        watchingSample: 3,
        finishedSample: 7,
        chartLabel: 'Exceptions each day',
        beforeTrend: [2, 3, 0],
        afterTrend: [0, 0],
        chartGoal: 0,
        chartGoalLabel: '0 exceptions',
        releaseGate: 'Webhook handler release confirmed',
        minimumEvidence: 'At least 5 affected 404 responses, plus warning telemetry',
        query: `SELECT toDate(timestamp) AS day, countIf(properties.result = 'exception') AS exceptions, countIf(properties.result = 'not_found') AS not_found, countIf(properties.result = 'warning') AS warnings\nFROM events WHERE event = 'example_webhook_result' AND timestamp >= {release_time}\nGROUP BY day ORDER BY day`,
        evidence: [
            { signal: 'Captured exceptions', baseline: '5', target: '0', watching: '0', finished: '0', result: 'met', watchingResult: 'met' },
            { signal: '404 responses', baseline: '6', target: '≥5', watching: '3', finished: '7', result: 'met', watchingResult: 'waiting' },
            { signal: 'Warnings for 404s', baseline: 'Not tracked', target: '1 per 404', watching: 'No signal', finished: 'No signal', result: 'missing', watchingResult: 'missing' },
        ],
        watchingSignal: 'missing_signal',
        verdict: 'inconclusive',
        reason: 'Exceptions stopped and 404s still appear. Warning telemetry is absent, so the visibility requirement is unverified.',
        nextStep: 'Check the warning destination before declaring success.',
    },
]
