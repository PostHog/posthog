import type { InboxItem, ReportView } from '@/model/types'

import { DEMO_AGENT, demoDecisionMeta } from './briefings'
import type { DemoLogEntry, DemoMutableState } from './demoMode'
import { DEMO_PEOPLE, type DemoFixture, type DemoFixtures } from './fixtures'

export type DemoView = Pick<
    DemoMutableState,
    'handed' | 'decisions' | 'snoozed' | 'closed' | 'read' | 'reviewers' | 'priorities' | 'log'
>

function lastIndexOfTag(log: DemoLogEntry[], tag: DemoLogEntry['tag']): number {
    return log.map((entry) => entry.tag).lastIndexOf(tag)
}

export function deriveDemoReport(view: DemoView, fixture: DemoFixture): ReportView {
    const base = fixture.report
    const id = base.id
    const handedAt = view.handed[id]
    const reviewerIds = view.reviewers[id]
    const log = view.log[id] ?? []
    const priority = view.priorities[id] ?? base.priority
    const report: ReportView = {
        ...base,
        ...(priority ? { priority } : {}),
        activity: [...base.activity, ...log.map(({ tag: _tag, ...event }) => event)],
    }
    const handed = Boolean(handedAt) && base.work.state !== 'done'
    if (handed) {
        report.task = {
            taskId: `${id}-handoff-task`,
            runId: `${id}-handoff-run`,
            status: 'in_progress',
            stage: fixture.briefing.handedStage,
            phase: 'working',
            connection: 'connected',
        }
        report.work = { state: 'working', assignee: { kind: 'task', name: DEMO_AGENT.name } }
        report.owner = { kind: 'agent', name: DEMO_AGENT.name }
    }
    if (reviewerIds) {
        report.reviewers = DEMO_PEOPLE.filter((person) => reviewerIds.includes(person.uuid)).map(
            ({ uuid, name, email }) => ({ uuid, name, email })
        )
        // Whichever of hand-off and reassign came last owns the report, as the log records them in order.
        if (!handed || lastIndexOfTag(log, 'reviewers') > lastIndexOfTag(log, 'handoff')) {
            const first = DEMO_PEOPLE.find((person) => person.uuid === reviewerIds[0])
            report.owner = first ? { kind: 'user', name: first.name } : { kind: 'none' }
        }
    }
    return report
}

export function deriveDemoInbox(view: DemoView, fixtures: DemoFixtures): InboxItem[] {
    const open = fixtures.list.filter(({ item }) => !view.closed[item.reportId])
    return open.map(({ item, briefing }) => {
        const id = item.reportId
        const next: InboxItem = { ...item, read: view.read[id] ?? item.read }
        const decision = view.decisions[id]
        if (decision) {
            next.needsInput = false
            next.progressLabel = decision.meta ?? demoDecisionMeta(decision.text)
        }
        if (view.handed[id] && item.state !== 'done') {
            next.agent = { ...DEMO_AGENT }
            next.progressLabel = briefing.handedStage
        }
        const snoozeLabel = view.snoozed[id]
        if (snoozeLabel && item.state !== 'done') {
            next.state = 'snoozed'
            next.snoozeLabel = snoozeLabel
            next.needsInput = false
        }
        return next
    })
}
