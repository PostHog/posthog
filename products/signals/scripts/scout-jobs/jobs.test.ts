import assert from 'node:assert/strict'
import { test } from 'node:test'

import type { SignalsScoutRunsListResponseShape2 } from '@posthog/sdk'

import { ScoutJobs, type ScoutApi } from './jobs.ts'

const now = (): Date => new Date('2024-01-15T00:00:00Z')
const run = (
    id: string,
    createdAt: string,
    overrides: Partial<SignalsScoutRunsListResponseShape2> = {}
): SignalsScoutRunsListResponseShape2 => ({
    run_id: id,
    skill_name: 'example-scout',
    skill_version: 1,
    status: 'completed',
    created_at: createdAt,
    started_at: createdAt,
    completed_at: createdAt,
    summary: '',
    error: '',
    failure_reason: null,
    emitted_count: 0,
    emitted_finding_ids: [],
    emitted_report_ids: [],
    edited_report_ids: [],
    task_id: null,
    task_run_id: null,
    task_url: null,
    metadata: {},
    ...overrides,
})

const api = (): ScoutApi => {
    const unexpected = async (): Promise<never> => {
        throw new Error('Unexpected API call')
    }
    return {
        context: async () => ({ projectId: 123, source: 'explicit' }),
        signals: {
            scoutProjectProfileGet: unexpected,
            scoutRunsList: unexpected,
            scoutNotesList: unexpected,
            scoutScratchpadSearch: unexpected,
            inboxReportsList: unexpected,
            inboxReportsRetrieve: unexpected,
            inboxReportArtefactsList: unexpected,
            scoutReportCheckList: unexpected,
        },
        errorTracking: { queryErrorTrackingIssuesList: unexpected, queryErrorTrackingIssue: unexpected },
    }
}

test('audit follows created_at cursors and counts report work when the legacy counter is zero', async () => {
    const client = api()
    const cursors: Array<string | undefined> = []
    const recent = run('new', '2024-01-14T00:00:00Z', {
        emitted_report_ids: ['report-a'],
        edited_report_ids: ['report-b'],
    })
    const older = run('old', '2024-01-13T00:00:00Z', { emitted_report_ids: ['report-a'], status: 'failed' })
    const pages = [[recent], [older], []]
    client.signals.scoutRunsList = async (input) => {
        cursors.push(input.date_to)
        return { data: { results: pages.shift()! }, meta: { status: 200 } } as Awaited<
            ReturnType<ScoutApi['signals']['scoutRunsList']>
        >
    }
    const result = await new ScoutJobs(client, now).audit({ from: '2024-01-01T00:00:00Z', to: now().toISOString() })
    assert.deepEqual(cursors, [now().toISOString(), recent.created_at, older.created_at])
    assert.equal(result.status, 'complete')
    assert.equal(result.data.uniqueAuthoredReports, 1)
    assert.equal(result.data.runsWithAuthoredReports, 2)
    assert.equal(result.data.runsWithEditedReports, 1)
    assert.equal(result.data.zeroLegacyCountWithReportWork, 2)
    assert.deepEqual(result.data.statuses, { completed: 1, failed: 1 })
})

test('audit reports a page cap as partial rather than claiming it covered the window', async () => {
    const client = api()
    client.signals.scoutRunsList = async () =>
        ({ data: { results: [run('one', '2024-01-14T00:00:00Z')] }, meta: { status: 200 } }) as Awaited<
            ReturnType<ScoutApi['signals']['scoutRunsList']>
        >
    const result = await new ScoutJobs(client, now).audit({
        from: '2024-01-01T00:00:00Z',
        to: now().toISOString(),
        maxPages: 1,
    })
    assert.equal(result.status, 'partial')
    assert.equal(result.data.coverage, 'page_cap')
})

test('a denied context read stays visible as a partial result', async () => {
    const client = api()
    const result = await new ScoutJobs(client, now).context({ skillName: 'example-scout' })
    assert.equal(result.status, 'partial')
    assert.equal(result.data.notes.data, null)
    assert.equal(result.data.notes.error?.message, 'Unexpected API call')
})

test('error baselines query each selected issue and do not invent zeroes for missing counts', async () => {
    const client = api()
    const windows: Array<{ id: string; from: string | undefined; to: string | null | undefined }> = []
    client.errorTracking.queryErrorTrackingIssuesList = async () =>
        ({
            data: {
                results: [
                    { id: 'issue-known', aggregations: { occurrences: 30 } },
                    { id: 'issue-unknown', aggregations: { occurrences: 20 } },
                ],
                hasMore: true,
                limit: 2,
                offset: 0,
                _posthogUrl: 'https://example.com/errors',
            },
            meta: { status: 200 },
        }) as Awaited<ReturnType<ScoutApi['errorTracking']['queryErrorTrackingIssuesList']>>
    client.errorTracking.queryErrorTrackingIssue = async (input) => {
        windows.push({ id: input.issueId, from: input.dateRange?.date_from, to: input.dateRange?.date_to })
        return {
            data: {
                id: input.issueId,
                impact: input.issueId === 'issue-known' ? { occurrences: 10 } : {},
                _posthogUrl: 'https://example.com/errors',
            },
            meta: { status: 200 },
        } as Awaited<ReturnType<ScoutApi['errorTracking']['queryErrorTrackingIssue']>>
    }
    const result = await new ScoutJobs(client, now).errors({ to: now().toISOString(), limit: 2 })
    assert.deepEqual(windows, [
        { id: 'issue-known', from: '2024-01-07T00:00:00.000Z', to: '2024-01-08T00:00:00.000Z' },
        { id: 'issue-unknown', from: '2024-01-07T00:00:00.000Z', to: '2024-01-08T00:00:00.000Z' },
    ])
    assert.equal(result.data.candidates[0].occurrenceRatio, 3)
    assert.equal(result.data.candidates[1].baselineOccurrences, null)
    assert.equal(result.data.candidates[1].assessment, 'baseline_missing')
    assert.equal(result.data.hasMoreCurrentIssues, true)
})

test('followups preserve an existing queued check instead of suggesting a duplicate', async () => {
    const client = api()
    client.signals.scoutReportCheckList = async () =>
        ({ data: [{ status: 'active', run_state: 'queued' }], meta: { status: 200 } }) as Awaited<
            ReturnType<ScoutApi['signals']['scoutReportCheckList']>
        >
    const result = await new ScoutJobs(client, now).followups({ reportIds: ['report-example'] })
    assert.equal(result.data.reports[0].queue, 'waiting')
    assert.equal(result.status, 'partial')
    assert.equal(result.data.reports[0].report.data, null)
})

test('large report evidence returns marked previews instead of the complete artifact bodies', async () => {
    const client = api()
    client.signals.inboxReportsRetrieve = async () =>
        ({ data: { id: 'report-example', summary: 's'.repeat(100_000) }, meta: { status: 200 } }) as Awaited<
            ReturnType<ScoutApi['signals']['inboxReportsRetrieve']>
        >
    client.signals.inboxReportArtefactsList = async () =>
        ({
            data: {
                count: 1,
                results: [
                    {
                        id: 'artefact-example',
                        type: 'note',
                        content: { text: 'a'.repeat(100_000) },
                        claim_id: null,
                        pull_request_id: null,
                        created_at: now().toISOString(),
                        updated_at: null,
                        actor_kind: 'system',
                        actor_agent: null,
                        created_by: null,
                        task_id: null,
                    },
                ],
                _posthogUrl: 'https://example.com/reports',
                _agentNote: '',
            },
            meta: { status: 200 },
        }) as Awaited<ReturnType<ScoutApi['signals']['inboxReportArtefactsList']>>
    const result = await new ScoutJobs(client, now).followups({ reportIds: ['report-example'] })
    const evidence = result.data.reports[0]
    assert.equal(evidence.report.data?.summaryTruncated, true)
    assert.equal(evidence.artefacts.data?.results[0].contentTruncated, true)
    assert.ok(JSON.stringify(result).length < 10_000)
})
