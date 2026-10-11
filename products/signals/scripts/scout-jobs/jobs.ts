import {
    PostHogError,
    type PostHogClient,
    type SignalsScoutNotesListData,
    type SignalsScoutProjectProfileGetData,
    type SignalsScoutRunsListResponseShape2,
    type SignalsScoutScratchpadSearchData,
    type SignalsScoutReportCheckListData,
    type SignalsInboxReportsRetrieveData,
    type SignalsInboxReportArtefactsListData,
    type ErrorTrackingQueryErrorTrackingIssuesListDataResultsItem,
    type ErrorTrackingQueryErrorTrackingIssueData,
} from '@posthog/sdk'

export interface ScoutApi {
    context: PostHogClient['context']
    signals: Pick<
        PostHogClient['signals'],
        | 'scoutProjectProfileGet'
        | 'scoutRunsList'
        | 'scoutNotesList'
        | 'scoutScratchpadSearch'
        | 'inboxReportsList'
        | 'inboxReportsRetrieve'
        | 'inboxReportArtefactsList'
        | 'scoutReportCheckList'
    >
    errorTracking: Pick<PostHogClient['errorTracking'], 'queryErrorTrackingIssuesList' | 'queryErrorTrackingIssue'>
}

export interface Section<T> {
    data: T | null
    error: { kind: string; status?: number; message: string } | null
}

export interface JobResult<T> {
    job: string
    projectId: number
    collectedAt: string
    status: 'complete' | 'partial'
    data: T
}

export interface ContextInput {
    skillName: string
    memoryText?: string
    runId?: string
    limit?: number
}

export interface ContextData {
    skillName: string
    scope: 'bounded_context'
    profile: Section<SignalsScoutProjectProfileGetData>
    recentRuns: Section<SignalsScoutRunsListResponseShape2[]>
    notes: Section<SignalsScoutNotesListData['results']>
    memory: Section<SignalsScoutScratchpadSearchData['results']>
    followups: Section<SignalsScoutScratchpadSearchData['results']>
}

export interface AuditInput {
    from: string
    to: string
    maxPages?: number
}

export interface ScoutRunCounts {
    skillName: string
    runs: number
    completed: number
    failed: number
    authored: number
    edited: number
}

export interface AuditData {
    window: { from: string; to: string }
    coverage: 'exhausted' | 'page_cap' | 'timestamp_boundary'
    pages: number
    runs: number
    statuses: Record<string, number>
    runsWithAuthoredReports: number
    runsWithEditedReports: number
    uniqueAuthoredReports: number
    uniqueEditedReports: number
    zeroLegacyCountWithReportWork: number
    scouts: ScoutRunCounts[]
}

export interface ErrorInput {
    to: string
    hours?: number
    limit?: number
    filterTestAccounts?: boolean
}

export interface ErrorCandidate {
    issue: ErrorTrackingQueryErrorTrackingIssuesListDataResultsItem
    baseline: Section<ErrorTrackingQueryErrorTrackingIssueData>
    currentOccurrences: number | null
    baselineOccurrences: number | null
    occurrenceRatio: number | null
    assessment: 'needs_review' | 'baseline_missing' | 'no_baseline_occurrences'
}

export interface ErrorData {
    current: { from: string; to: string }
    baseline: { from: string; to: string }
    hasMoreCurrentIssues: boolean
    candidates: ErrorCandidate[]
}

export interface FollowupInput {
    limit?: number
    reportIds?: string[]
}

export interface ReportEvidence {
    reportId: string
    report: Section<ReportSnapshot>
    checks: Section<SignalsScoutReportCheckListData>
    artefacts: Section<ArtefactIndex>
    memory: Section<SignalsScoutScratchpadSearchData>
    queue: 'due' | 'waiting' | 'review_needed' | 'unknown'
}

export interface ReportSnapshot extends Pick<
    SignalsInboxReportsRetrieveData,
    'id' | 'title' | 'status' | 'updated_at' | 'implementation_pr_url' | 'implementation_pr_state'
> {
    summaryPreview: string
    summaryTruncated: boolean
}

export interface ArtefactIndex {
    count: number
    hasMore: boolean
    url: string
    results: Array<{
        id: string
        type: string
        createdAt: string
        contentPreview: string
        contentTruncated: boolean
    }>
}

export interface FollowupData {
    selection: 'explicit_ids' | 'recently_resolved'
    hasMoreReports: boolean
    reports: ReportEvidence[]
}

export class ScoutJobs {
    private api: ScoutApi
    private now: () => Date

    constructor(api: ScoutApi, now: () => Date = () => new Date()) {
        this.api = api
        this.now = now
    }

    private limit(value: number | undefined, fallback: number, max: number): number {
        const result = value ?? fallback
        if (!Number.isInteger(result) || result < 1 || result > max) {
            throw new Error(`Expected an integer between 1 and ${max}`)
        }
        return result
    }

    private timestamp(value: string): number {
        const result = Date.parse(value)
        if (!Number.isFinite(result) || !/(Z|[+-]\d\d:\d\d)$/.test(value)) {
            throw new Error('Expected an ISO timestamp with an explicit timezone')
        }
        return result
    }

    private async section<T>(request: () => Promise<T>): Promise<Section<T>> {
        try {
            return { data: await request(), error: null }
        } catch (error) {
            return {
                data: null,
                error: {
                    kind: error instanceof PostHogError ? error.details.kind : 'request',
                    ...(error instanceof PostHogError ? { status: error.details.status } : {}),
                    message: error instanceof Error ? error.message : 'Request failed',
                },
            }
        }
    }

    private async result<T>(job: string, data: T, complete: boolean): Promise<JobResult<T>> {
        return {
            job,
            projectId: (await this.api.context()).projectId,
            collectedAt: this.now().toISOString(),
            status: complete ? 'complete' : 'partial',
            data,
        }
    }

    private reportSnapshot(report: SignalsInboxReportsRetrieveData): ReportSnapshot {
        const summary = report.summary ?? ''
        return {
            id: report.id,
            title: report.title,
            status: report.status,
            updated_at: report.updated_at,
            implementation_pr_url: report.implementation_pr_url,
            implementation_pr_state: report.implementation_pr_state,
            summaryPreview: summary.slice(0, 3000),
            summaryTruncated: summary.length > 3000,
        }
    }

    private artefactIndex(artefacts: SignalsInboxReportArtefactsListData): ArtefactIndex {
        return {
            count: artefacts.count,
            hasMore: Boolean(artefacts.next),
            url: artefacts._posthogUrl,
            results: artefacts.results.map((artefact) => {
                const content = JSON.stringify(artefact.content)
                return {
                    id: artefact.id,
                    type: artefact.type,
                    createdAt: artefact.created_at,
                    contentPreview: content.slice(0, 1000),
                    contentTruncated: content.length > 1000,
                }
            }),
        }
    }

    async context(input: ContextInput): Promise<JobResult<ContextData>> {
        if (!input.skillName.trim()) {
            throw new Error('skillName is required')
        }
        const limit = this.limit(input.limit, 10, 50)
        const [profile, recentRuns, notes, memory, followups] = await Promise.all([
            this.section(
                async () =>
                    (await this.api.signals.scoutProjectProfileGet({ run_id: input.runId, summary_only: true })).data
            ),
            this.section(
                async () => (await this.api.signals.scoutRunsList({ skill_name: input.skillName, limit })).data.results
            ),
            this.section(
                async () =>
                    (
                        await this.api.signals.scoutNotesList({
                            skill_name: input.skillName,
                            include_general: true,
                            content_max_chars: 1500,
                            limit,
                        })
                    ).data.results
            ),
            this.section(
                async () =>
                    (
                        await this.api.signals.scoutScratchpadSearch({
                            text: input.memoryText ?? input.skillName,
                            content_max_chars: 1500,
                            limit,
                        })
                    ).data.results
            ),
            this.section(
                async () =>
                    (
                        await this.api.signals.scoutScratchpadSearch({
                            text: `followup:${input.skillName}:`,
                            content_max_chars: 1500,
                            limit,
                        })
                    ).data.results
            ),
        ])
        return this.result(
            'context',
            { skillName: input.skillName, scope: 'bounded_context', profile, recentRuns, notes, memory, followups },
            [profile, recentRuns, notes, memory, followups].every((section) => section.error === null)
        )
    }

    async audit(input: AuditInput): Promise<JobResult<AuditData>> {
        if (this.timestamp(input.from) >= this.timestamp(input.to)) {
            throw new Error('from must precede to')
        }
        const maxPages = this.limit(input.maxPages, 100, 250)
        const runs = new Map<string, SignalsScoutRunsListResponseShape2>()
        let cursor = input.to
        let pages = 0
        let coverage: AuditData['coverage'] = 'page_cap'
        while (pages < maxPages) {
            const page = (await this.api.signals.scoutRunsList({ date_from: input.from, date_to: cursor, limit: 100 }))
                .data.results
            pages++
            if (!page.length) {
                coverage = 'exhausted'
                break
            }
            for (const run of page) {
                runs.set(run.run_id, run)
            }
            const oldest = page.at(-1)!.created_at
            if (oldest >= cursor) {
                throw new Error('The run cursor did not advance')
            }
            // An exclusive timestamp cursor cannot prove coverage across a full page ending in a tie.
            if (page.length === 100 && page.filter((run) => run.created_at === oldest).length > 1) {
                coverage = 'timestamp_boundary'
                break
            }
            cursor = oldest
        }
        const statuses: Record<string, number> = {}
        const scouts = new Map<string, ScoutRunCounts>()
        const authored = new Set<string>()
        const edited = new Set<string>()
        let runsWithAuthoredReports = 0
        let runsWithEditedReports = 0
        let zeroLegacyCountWithReportWork = 0
        for (const run of runs.values()) {
            statuses[run.status] = (statuses[run.status] ?? 0) + 1
            const scout = scouts.get(run.skill_name) ?? {
                skillName: run.skill_name,
                runs: 0,
                completed: 0,
                failed: 0,
                authored: 0,
                edited: 0,
            }
            scout.runs++
            scout.completed += Number(run.status === 'completed')
            scout.failed += Number(run.status === 'failed')
            scout.authored += Number(run.emitted_report_ids.length > 0)
            scout.edited += Number(run.edited_report_ids.length > 0)
            scouts.set(run.skill_name, scout)
            runsWithAuthoredReports += Number(run.emitted_report_ids.length > 0)
            runsWithEditedReports += Number(run.edited_report_ids.length > 0)
            zeroLegacyCountWithReportWork += Number(
                run.emitted_count === 0 && (run.emitted_report_ids.length > 0 || run.edited_report_ids.length > 0)
            )
            run.emitted_report_ids.forEach((id) => authored.add(id))
            run.edited_report_ids.forEach((id) => edited.add(id))
        }
        return this.result(
            'audit',
            {
                window: { from: input.from, to: input.to },
                coverage,
                pages,
                runs: runs.size,
                statuses,
                runsWithAuthoredReports,
                runsWithEditedReports,
                uniqueAuthoredReports: authored.size,
                uniqueEditedReports: edited.size,
                zeroLegacyCountWithReportWork,
                scouts: [...scouts.values()].sort((a, b) => b.runs - a.runs),
            },
            coverage === 'exhausted'
        )
    }

    async errors(input: ErrorInput): Promise<JobResult<ErrorData>> {
        const hours = this.limit(input.hours, 24, 168)
        const limit = this.limit(input.limit, 5, 20)
        const end = this.timestamp(input.to)
        const current = { from: new Date(end - hours * 3600000).toISOString(), to: new Date(end).toISOString() }
        const baseline = {
            from: new Date(end - (hours + 168) * 3600000).toISOString(),
            to: new Date(end - 168 * 3600000).toISOString(),
        }
        const filterTestAccounts = input.filterTestAccounts ?? true
        const list = await this.api.errorTracking.queryErrorTrackingIssuesList({
            dateRange: { date_from: current.from, date_to: current.to },
            status: 'active',
            orderBy: 'occurrences',
            orderDirection: 'DESC',
            limit,
            filterTestAccounts,
        })
        const candidates: ErrorCandidate[] = []
        for (const issue of list.data.results) {
            // Fetch each selected issue's baseline directly; absence from a top-N list is not a zero.
            const previous = await this.section(
                async () =>
                    (
                        await this.api.errorTracking.queryErrorTrackingIssue({
                            issueId: issue.id,
                            dateRange: { date_from: baseline.from, date_to: baseline.to },
                            filterTestAccounts,
                        })
                    ).data
            )
            const currentOccurrences = issue.aggregations?.occurrences ?? null
            const baselineOccurrences = previous.data?.impact?.occurrences ?? null
            candidates.push({
                issue,
                baseline: previous,
                currentOccurrences,
                baselineOccurrences,
                occurrenceRatio:
                    currentOccurrences !== null && baselineOccurrences !== null && baselineOccurrences > 0
                        ? currentOccurrences / baselineOccurrences
                        : null,
                assessment:
                    baselineOccurrences === null
                        ? 'baseline_missing'
                        : baselineOccurrences === 0
                          ? 'no_baseline_occurrences'
                          : 'needs_review',
            })
        }
        return this.result(
            'errors',
            { current, baseline, hasMoreCurrentIssues: list.data.hasMore, candidates },
            candidates.every((candidate) => !candidate.baseline.error)
        )
    }

    async followups(input: FollowupInput): Promise<JobResult<FollowupData>> {
        const limit = this.limit(input.limit, 5, 20)
        if (
            input.reportIds &&
            (!input.reportIds.length || input.reportIds.length > limit || input.reportIds.some((id) => !id.trim()))
        ) {
            throw new Error('reportIds must contain between 1 and limit non-empty IDs')
        }
        const listed = input.reportIds
            ? null
            : (
                  await this.api.signals.inboxReportsList({
                      status: 'resolved',
                      ordering: '-updated_at',
                      limit,
                      include_source_metadata: false,
                  })
              ).data
        const ids = [...new Set(input.reportIds ?? listed!.results.map((report) => report.id))]
        const reports: ReportEvidence[] = []
        for (const reportId of ids) {
            const [report, checks, artefacts, memory] = await Promise.all([
                this.section(async () =>
                    this.reportSnapshot((await this.api.signals.inboxReportsRetrieve({ id: reportId })).data)
                ),
                this.section(async () => (await this.api.signals.scoutReportCheckList({ report_id: reportId })).data),
                this.section(async () =>
                    this.artefactIndex(
                        (await this.api.signals.inboxReportArtefactsList({ report_id: reportId, limit: 20 })).data
                    )
                ),
                this.section(
                    async () =>
                        (
                            await this.api.signals.scoutScratchpadSearch({
                                text: reportId,
                                limit: 10,
                                content_max_chars: 1500,
                            })
                        ).data
                ),
            ])
            const queue = checks.error
                ? 'unknown'
                : checks.data?.some((check) => ['due', 'stale'].includes(check.run_state))
                  ? 'due'
                  : checks.data?.some((check) => ['pending', 'active'].includes(check.status))
                    ? 'waiting'
                    : 'review_needed'
            reports.push({ reportId, report, checks, artefacts, memory, queue })
        }
        return this.result(
            'followups',
            {
                selection: input.reportIds ? 'explicit_ids' : 'recently_resolved',
                hasMoreReports: Boolean(listed?.next),
                reports,
            },
            reports.every((report) =>
                [report.report, report.checks, report.artefacts, report.memory].every((section) => !section.error)
            )
        )
    }
}
