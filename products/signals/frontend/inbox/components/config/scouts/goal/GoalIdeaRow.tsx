import { useActions, useValues } from 'kea'

import {
    IconBug,
    IconDocument,
    IconEllipsis,
    IconFlask,
    IconGraph,
    IconLightBulb,
    IconRewindPlay,
    IconTrends,
} from '@posthog/icons'
import { LemonButton, LemonDialog, LemonMenu, type LemonMenuItems, type LemonTagType } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { GoalScoutDetailApi, GoalScoutWorkApi } from 'products/signals/frontend/generated/api.schemas'

import { goalScoutLogic } from '../../../../logics/goal/goalScoutLogic'
import { ASSESSMENT_LABELS, ideaAssessment, ideaEvidence, ideaLead } from '../../../../utils/goal/ideas'
import { GoalDismissForm } from './GoalDismissForm'
import { type GoalLink, GoalLinkList } from './GoalLinkList'
import { GoalRow } from './GoalRow'
import { GoalStat } from './GoalStat'
import { GoalTestPlan } from './GoalTestPlan'

const ASSESSMENT_TAGS: Record<string, LemonTagType> = {
    supported: 'success',
    pending: 'default',
    not_supported: 'warning',
    no_verdict: 'muted',
}

const ASSESSMENT_TOOLTIPS: Record<string, string> = {
    supported: 'Your data backs this idea. The scout found evidence that this change can move the measure.',
    not_supported:
        'Your data does not back this idea yet. The scout found no evidence that this change would move the measure. You can still build and test it.',
    pending: 'The scout is checking this idea against your data.',
}

const ASSESSMENT_REASONS: Record<string, string> = {
    pending: 'The scout checks this idea against your data.',
    no_verdict: 'The scout did not rate its confidence in this idea. Open the report to decide.',
}

const EVIDENCE_ICONS: Record<string, JSX.Element> = {
    replay: <IconRewindPlay />,
    insight: <IconGraph />,
    chart: <IconTrends />,
    experiment: <IconFlask />,
    error: <IconBug />,
}

function evidenceLinks(item: GoalScoutWorkApi): GoalLink[] {
    const report = item.report_id ? urls.inboxReport('reports', item.report_id) : undefined
    const links: GoalLink[] = ideaEvidence(item).map((entry, index) => ({
        key: `${entry.url}-${index}`,
        icon: EVIDENCE_ICONS[entry.kind] ?? <IconGraph />,
        label: capitalizeFirstLetter(entry.label),
        to: entry.url.startsWith('chart:') ? report : entry.url || undefined,
        dataAttr: `goal-idea-evidence-${entry.kind}`,
    }))
    if (report) {
        links.push({ key: 'report', icon: <IconDocument />, label: 'Report', to: report, dataAttr: 'goal-idea-report' })
    }
    return links
}

export function GoalIdeaRow({ item, goal }: { item: GoalScoutWorkApi; goal: GoalScoutDetailApi }): JSX.Element {
    const { busy, busyOperation, buildDisabledReason, dismissingIdea, openIdea, ideaInProgress, ideaPlans } = useValues(
        goalScoutLogic({ id: goal.id })
    )
    const { openBuild, openDismiss, setExpandedIdea, act } = useActions(goalScoutLogic({ id: goal.id }))
    const assessment = ideaAssessment(item)
    const explanation = ideaLead(item) || ASSESSMENT_REASONS[assessment] || ''
    const links = evidenceLinks(item)
    const plan = ideaPlans[item.id]?.draft
    const unchecked = item.source === 'owner' && !item.report_id
    const expanded = openIdea === item.id
    const building = busyOperation === `build:${item.id}`
    const canBuild = goal.is_owner && !ideaInProgress
    const menuItems: LemonMenuItems = [
        goal.is_owner && item.report_id
            ? {
                  label: 'Dismiss idea',
                  onClick: () => {
                      setExpandedIdea(item.id)
                      openDismiss(item.id)
                  },
                  'data-attr': 'goal-idea-dismiss',
              }
            : null,
        goal.is_owner && unchecked
            ? {
                  label: 'Dismiss idea',
                  disabledReason: busy ? 'Saving a change' : undefined,
                  onClick: () =>
                      LemonDialog.open({
                          title: 'Dismiss this idea?',
                          description: 'The scout will not check this idea.',
                          primaryButton: {
                              children: 'Dismiss idea',
                              status: 'danger',
                              onClick: () => act(item.id, 'drop'),
                              'data-attr': 'goal-idea-remove-confirm',
                          },
                          secondaryButton: { children: 'Cancel' },
                      }),
                  'data-attr': 'goal-idea-remove',
              }
            : null,
        item.report_id
            ? {
                  label: 'Open the report in the inbox',
                  to: urls.inboxReport('reports', item.report_id),
                  'data-attr': 'goal-idea-open-report',
              }
            : null,
    ]
    return (
        <GoalRow
            icon={<IconLightBulb className="size-4 text-warning" />}
            title={item.title}
            tag={
                ASSESSMENT_LABELS[assessment]
                    ? {
                          label: ASSESSMENT_LABELS[assessment],
                          type: ASSESSMENT_TAGS[assessment] ?? 'default',
                          tooltip: ASSESSMENT_TOOLTIPS[assessment],
                      }
                    : undefined
            }
            actions={
                <>
                    {canBuild && (
                        <LemonButton
                            size="small"
                            type={item.assessment === 'supported' ? 'primary' : 'secondary'}
                            loading={building}
                            disabledReason={buildDisabledReason ?? (busy && !building ? 'Saving a change' : undefined)}
                            onClick={() => openBuild(item.id)}
                            data-attr="goal-idea-build"
                        >
                            {item.assessment === 'not_supported' ? 'Build anyway' : 'Build and test'}
                        </LemonButton>
                    )}
                    {menuItems.some(Boolean) && (
                        <LemonMenu items={menuItems} placement="bottom-end">
                            <LemonButton size="small" icon={<IconEllipsis />} aria-label="More actions" />
                        </LemonMenu>
                    )}
                </>
            }
            expanded={expanded}
            onToggle={() => setExpandedIdea(expanded ? null : item.id)}
            dataAttr="goal-idea"
        >
            {explanation && <p className="m-0 max-w-[72ch] text-sm leading-relaxed text-primary">{explanation}</p>}
            <GoalTestPlan
                audience={plan?.audience ? Number(plan.audience) : null}
                days={plan?.days ? Number(plan.days) : null}
                metric={goal.goal_metric}
            />
            {item.moves_metric && <GoalStat label="Moves" value={item.moves_metric} />}
            {links.length > 0 && (
                <div className="flex flex-col gap-1.5">
                    <span className="text-xs text-tertiary">Evidence</span>
                    <GoalLinkList links={links} layout="column" />
                </div>
            )}
            {goal.is_owner && dismissingIdea === item.id && <GoalDismissForm goalId={goal.id} workId={item.id} />}
        </GoalRow>
    )
}
