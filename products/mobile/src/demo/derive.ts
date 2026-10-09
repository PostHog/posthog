import type { Fact, InboxItem, ReportView } from '@/model/types'

import { DEMO_AGENT, demoDecisionMeta } from './briefings'
import type { DemoMutableState } from './demoMode'
import { DEMO_PEOPLE, type DemoFixture, type DemoFixtures } from './fixtures'

export type DemoView = Pick<DemoMutableState, 'handed' | 'decisions' | 'snoozed' | 'read' | 'reviewers' | 'log'>

function ownerAfterHandOff(facts: Fact[]): Fact[] {
    return facts.map((fact) =>
        fact.key === 'Owner'
            ? { key: fact.key, title: DEMO_AGENT.name, sub: 'Picked up just now', tone: 'agent' }
            : fact
    )
}

export function deriveDemoReport(view: DemoView, fixture: DemoFixture): ReportView {
    const base = fixture.report
    const id = base.id
    const handedAt = view.handed[id]
    const reviewerIds = view.reviewers[id]
    const report: ReportView = {
        ...base,
        activity: [...base.activity, ...(view.log[id] ?? []).map(({ tag: _tag, ...event }) => event)],
    }
    if (reviewerIds) {
        report.reviewers = DEMO_PEOPLE.filter((person) => reviewerIds.includes(person.uuid)).map(
            ({ uuid, name, email }) => ({ uuid, name, email })
        )
    }
    if (handedAt && base.work.state !== 'done') {
        report.task = {
            taskId: `${id}-handoff-task`,
            runId: `${id}-handoff-run`,
            status: 'in_progress',
            stage: fixture.briefing.handedStage,
        }
        report.work = { state: 'working', assignee: { kind: 'task', name: DEMO_AGENT.name } }
        report.facts = ownerAfterHandOff(base.facts)
    }
    return report
}

export function deriveDemoInbox(view: DemoView, fixtures: DemoFixtures): InboxItem[] {
    return fixtures.list.map(({ item, briefing }) => {
        const id = item.reportId
        const next: InboxItem = { ...item, read: Boolean(view.read[id]) }
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
