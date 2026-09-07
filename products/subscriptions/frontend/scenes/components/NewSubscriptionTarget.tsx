import { useActions, useValues } from 'kea'

import { IconDashboard, IconGraph, IconSparkles } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'

import { dashboardsModel } from '~/models/dashboardsModel'
import { InsightShortId } from '~/types'

import { newSubscriptionTargetLogic, NewSubscriptionTargetKind } from '../newSubscriptionTargetLogic'

interface NewSubscriptionTargetProps {
    aiSubscriptionsAvailable: boolean
    onCancel: () => void
}

const KIND_LABELS: Record<NewSubscriptionTargetKind, string> = {
    insight: 'An insight',
    dashboard: 'A dashboard',
    ai: 'An AI prompt',
}

/**
 * First step of creating a subscription from the subscriptions scene. Elsewhere the
 * subscription is created from the insight or dashboard it sends, so the form already
 * knows what to snapshot; here the user picks that first.
 */
export function NewSubscriptionTarget({ aiSubscriptionsAvailable, onCancel }: NewSubscriptionTargetProps): JSX.Element {
    const { kind, insightOptions, insightOptionsLoading } = useValues(newSubscriptionTargetLogic)
    const { setKind, setInsightSearch, chooseInsight, chooseDashboard, chooseAiPrompt } =
        useActions(newSubscriptionTargetLogic)
    const { nameSortedDashboards, dashboardsLoading } = useValues(dashboardsModel)

    const kinds: { key: NewSubscriptionTargetKind; icon: JSX.Element }[] = [
        { key: 'insight', icon: <IconGraph /> },
        { key: 'dashboard', icon: <IconDashboard /> },
        ...(aiSubscriptionsAvailable ? [{ key: 'ai' as const, icon: <IconSparkles /> }] : []),
    ]

    return (
        <div className="flex flex-col gap-4">
            <LemonLabel>What should we send?</LemonLabel>
            <div className="flex flex-wrap gap-2">
                {kinds.map(({ key, icon }) => (
                    <LemonButton
                        key={key}
                        type={kind === key ? 'primary' : 'secondary'}
                        icon={icon}
                        data-attr={`new-subscription-target-${key}`}
                        onClick={() => (key === 'ai' ? chooseAiPrompt() : setKind(key))}
                    >
                        {KIND_LABELS[key]}
                    </LemonButton>
                ))}
            </div>

            {kind === 'insight' && (
                <LemonInputSelect
                    mode="single"
                    placeholder="Search your saved insights"
                    value={[]}
                    onInputChange={setInsightSearch}
                    onChange={(values) => {
                        const shortId = values[0] as InsightShortId | undefined
                        const picked = insightOptions.find((option) => option.shortId === shortId)
                        if (shortId && picked) {
                            chooseInsight(shortId, picked.name)
                        }
                    }}
                    options={insightOptions.map((option) => ({ key: option.shortId, label: option.name }))}
                    loading={insightOptionsLoading}
                    // The search runs on the server, so the list is already the answer to it.
                    disableFiltering
                    data-attr="new-subscription-insight-select"
                />
            )}

            {kind === 'dashboard' && (
                <LemonInputSelect
                    mode="single"
                    placeholder="Search your dashboards"
                    value={[]}
                    onChange={(values) => {
                        const id = Number(values[0])
                        const picked = nameSortedDashboards.find((dashboard) => dashboard.id === id)
                        if (picked) {
                            chooseDashboard(id, picked.name || 'Untitled')
                        }
                    }}
                    options={nameSortedDashboards.map((dashboard) => ({
                        key: String(dashboard.id),
                        label: dashboard.name || 'Untitled',
                    }))}
                    loading={dashboardsLoading}
                    data-attr="new-subscription-dashboard-select"
                />
            )}

            <div className="flex justify-end">
                <LemonButton type="secondary" onClick={onCancel}>
                    Cancel
                </LemonButton>
            </div>
        </div>
    )
}
