import { SignalReport, SignalReportArtefact } from '../../../types'
import { parsePrUrlParts } from '../../../utils/reportPresentation'
import { prettifyScoutSkillName } from '../../../utils/scoutRunsWindow'
import {
    CheckScheduledContent,
    CommitContent,
    NoteContent,
    selectVisibleReportActivity,
    TaskRunArtefactContent,
} from '../artefactTypes'

export type ReportActivityActor =
    | { kind: 'person'; name: string; email?: string }
    | { kind: 'scout'; name: string }
    | { kind: 'posthog'; name: string }

export interface ReportActivityEntry {
    id: string
    at: string
    actor: ReportActivityActor
    /** What the actor did, read after the actor's name. */
    action: string
    /** A value the action names, such as a status or a priority. */
    badge?: { label: string; variant: 'default' | 'info' }
    /** What the action was done to, such as a commit message or a pull request. */
    reference?: { text: string; mono?: boolean; url?: string }
    /** Markdown shown under the line: the text of a note. */
    body?: string
}

const POSTHOG_AGENT: ReportActivityActor = { kind: 'posthog', name: 'PostHog agent' }
const POSTHOG: ReportActivityActor = { kind: 'posthog', name: 'PostHog' }

const VERIFICATION_PLAN_HEADING = /^## Verification plan\s*/

function actorOf(artefact: SignalReportArtefact): ReportActivityActor {
    if (artefact.created_by) {
        return {
            kind: 'person',
            name: artefact.created_by.first_name?.trim() || artefact.created_by.email,
            email: artefact.created_by.email,
        }
    }
    const author = artefact.type === 'note' ? (artefact.content as NoteContent).author : null
    return author ? { kind: 'scout', name: `${prettifyScoutSkillName(author)} scout` } : POSTHOG_AGENT
}

function entryFor(artefact: SignalReportArtefact): Omit<ReportActivityEntry, 'id' | 'at' | 'actor'> | null {
    switch (artefact.type) {
        case 'note': {
            const note = (artefact.content as NoteContent).note ?? ''
            return VERIFICATION_PLAN_HEADING.test(note)
                ? { action: 'wrote the verification plan', body: note.replace(VERIFICATION_PLAN_HEADING, '') }
                : { action: 'commented', body: note }
        }
        case 'commit':
            return {
                action: 'pushed a commit',
                reference: { text: (artefact.content as CommitContent).message, mono: true },
            }
        case 'pull_request': {
            const url = String(artefact.content.url ?? '')
            const parts = parsePrUrlParts(url)
            return {
                action: 'opened pull request',
                reference: parts ? { text: `${parts.repoSlug}#${parts.number}`, mono: true, url } : undefined,
            }
        }
        case 'work_claim':
            return { action: 'claimed this report' }
        case 'work_release':
            return { action: 'released this report' }
        case 'task_run': {
            const type = (artefact.content as TaskRunArtefactContent).type
            return type === 'research' || type === 'implementation' ? { action: `started the ${type} run` } : null
        }
        case 'check_scheduled': {
            const title = (artefact.content as CheckScheduledContent).title
            return { action: 'scheduled a follow-up check', reference: title ? { text: title } : undefined }
        }
        case 'priority_judgment':
            return {
                action: 'set the priority to',
                badge: { label: String(artefact.content.priority), variant: 'default' },
            }
        default:
            return null
    }
}

/**
 * The report's work log as a feed, newest first: one line per thing a person or an agent did.
 * Pipeline bookkeeping (ranking scores, safety and repo judgments) is left out.
 */
export function reportActivityEntries(
    report: Pick<SignalReport, 'monitoring_started_at'>,
    artefacts: SignalReportArtefact[]
): ReportActivityEntry[] {
    const entries: ReportActivityEntry[] = []
    for (const artefact of selectVisibleReportActivity(artefacts)) {
        const entry = entryFor(artefact)
        if (entry) {
            entries.push({ id: artefact.id, at: artefact.created_at, actor: actorOf(artefact), ...entry })
        }
    }
    if (report.monitoring_started_at) {
        entries.push({
            id: 'monitoring-started',
            at: report.monitoring_started_at,
            actor: POSTHOG,
            action: 'changed status to',
            badge: { label: 'Monitoring', variant: 'info' },
        })
    }
    return entries.sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
}
