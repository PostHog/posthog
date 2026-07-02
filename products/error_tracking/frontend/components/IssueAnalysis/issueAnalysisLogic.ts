import { afterMount, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import type { SignalNode } from 'scenes/debug/signals/types'
import { SignalReport, SignalReportArtefact, SignalReportStatus } from 'scenes/inbox/types'
import { canCreateImplementationPr } from 'scenes/inbox/utils/reportPresentation'

import type { issueAnalysisLogicType } from './issueAnalysisLogicType'

export interface IssueAnalysisLogicProps {
    issueId: string
}

/** A `signal_finding` artefact narrowed to one of this issue's signals: where the research agent looked. */
export interface IssueFinding {
    signalId: string
    codePaths: string[]
    commits: { sha: string; reason: string }[]
    verified: boolean
}

export type IssueAnalysisCta = 'create_pr' | 'view_pr' | 'in_progress' | null

// Statuses meaning a research run is queued or currently executing for the report.
const RESEARCH_PENDING_STATUSES: SignalReportStatus[] = [SignalReportStatus.CANDIDATE, SignalReportStatus.IN_PROGRESS]

/**
 * An issue's created/reopened/spiking signals can land in several reports over time — surface the
 * one with the freshest activity.
 */
export function pickPrimaryReport(reports: SignalReport[] | null): SignalReport | null {
    if (!reports?.length) {
        return null
    }
    return [...reports].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
}

export function isResearchPending(report: SignalReport | null): boolean {
    if (!report) {
        return false
    }
    // `potential` without a title is a fresh group whose first research run hasn't started yet;
    // `potential` with one is a researched report reset by the actionability judge — show it as-is.
    return (
        RESEARCH_PENDING_STATUSES.includes(report.status) ||
        (report.status === SignalReportStatus.POTENTIAL && !report.title)
    )
}

export function deriveIssueAnalysisCta(report: SignalReport | null): IssueAnalysisCta {
    if (!report) {
        return null
    }
    if (report.implementation_pr_url) {
        return 'view_pr'
    }
    if (canCreateImplementationPr(report)) {
        return 'create_pr'
    }
    if (isResearchPending(report)) {
        return 'in_progress'
    }
    return null
}

/**
 * Narrow a report's `signal_finding` artefacts to the given issue's signals. Artefacts are
 * newest-first and finding identity is per signal, so the first row seen per signal wins.
 */
export function extractIssueFindings(
    issueId: string,
    signals: SignalNode[],
    artefacts: SignalReportArtefact[]
): IssueFinding[] {
    const issueSignalIds = new Set(
        signals.filter((s) => s.source_product === 'error_tracking' && s.source_id === issueId).map((s) => s.signal_id)
    )
    const findings: IssueFinding[] = []
    const seen = new Set<string>()
    for (const artefact of artefacts) {
        if (artefact.type !== 'signal_finding') {
            continue
        }
        const signalId = artefact.content?.signal_id
        if (typeof signalId !== 'string' || !issueSignalIds.has(signalId) || seen.has(signalId)) {
            continue
        }
        seen.add(signalId)
        const codePaths = Array.isArray(artefact.content.relevant_code_paths)
            ? artefact.content.relevant_code_paths.filter((p): p is string => typeof p === 'string')
            : []
        const rawCommits = artefact.content.relevant_commit_hashes
        const commits =
            rawCommits && typeof rawCommits === 'object' && !Array.isArray(rawCommits)
                ? Object.entries(rawCommits as Record<string, unknown>).map(([sha, reason]) => ({
                      sha,
                      reason: typeof reason === 'string' ? reason : '',
                  }))
                : []
        if (codePaths.length || commits.length) {
            findings.push({ signalId, codePaths, commits, verified: !!artefact.content.verified })
        }
    }
    return findings
}

export const issueAnalysisLogic = kea<issueAnalysisLogicType>([
    props({} as IssueAnalysisLogicProps),
    key((props) => props.issueId),
    path((key) => ['products', 'error_tracking', 'issueAnalysisLogic', key]),

    loaders(({ props, values }) => ({
        reports: [
            null as SignalReport[] | null,
            {
                loadReports: async () => {
                    const response = await api.signalReports.list({
                        source_product: 'error_tracking',
                        source_id: props.issueId,
                        limit: 20,
                    })
                    return response.results
                },
            },
        ],
        issueFindings: [
            [] as IssueFinding[],
            {
                loadIssueFindings: async () => {
                    const report = values.report
                    if (!report) {
                        return []
                    }
                    const [{ signals }, artefacts] = await Promise.all([
                        api.signalReports.getReportSignals(report.id),
                        api.signalReports.artefacts(report.id, { limit: 1000 }),
                    ])
                    return extractIssueFindings(props.issueId, signals, artefacts.results)
                },
            },
        ],
    })),

    selectors({
        report: [(s) => [s.reports], (reports): SignalReport | null => pickPrimaryReport(reports)],
        researchPending: [(s) => [s.report], (report): boolean => isResearchPending(report)],
        cta: [(s) => [s.report], (report): IssueAnalysisCta => deriveIssueAnalysisCta(report)],
        showCard: [
            (s) => [s.report, s.researchPending],
            (report, researchPending): boolean => !!report && (!!report.title || !!report.summary || researchPending),
        ],
    }),

    listeners(({ actions, values, props }) => ({
        loadReportsSuccess: () => {
            const report = values.report
            if (!report) {
                return
            }
            actions.loadIssueFindings()
            posthog.capture('error_tracking_issue_analysis_shown', {
                issue_id: props.issueId,
                report_id: report.id,
                report_status: report.status,
                priority: report.priority ?? null,
                actionability: report.actionability ?? null,
                has_implementation_pr: !!report.implementation_pr_url,
            })
        },
    })),

    afterMount(({ actions }) => {
        actions.loadReports()
    }),
])
