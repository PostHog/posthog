import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { WorkflowSavedView } from './workflowSavedViews'

export interface WorkflowSavedViewTabsRowProps {
    views: WorkflowSavedView[]
    activeViewId: string
    viewCounts: Record<string, number>
    isModified: boolean
    activeViewChanges: string[]
    onApplyView: (view: WorkflowSavedView) => void
    max: number
}

export function WorkflowSavedViewTabsRow({
    views,
    activeViewId,
    viewCounts,
    isModified,
    activeViewChanges,
    onApplyView,
    max,
}: WorkflowSavedViewTabsRowProps): JSX.Element {
    const visible = views.slice(0, max)
    const active = views.find((view) => view.id === activeViewId)
    if (views.length > max && active && !visible.includes(active)) {
        visible[visible.length - 1] = active
    }
    const overflow = views.filter((view) => !visible.includes(view))
    const label = (view: WorkflowSavedView): JSX.Element => (
        <Tooltip title={view.name}>
            <span className="inline-flex min-w-0 max-w-56 items-center whitespace-nowrap">
                <span className="truncate">{view.name}&nbsp;</span>
                <span className="shrink-0 text-secondary" translate="no">
                    {viewCounts[view.id] ?? ''}
                </span>
                {view.id === activeViewId && isModified && (
                    <span
                        className="ml-1.5 size-1.5 shrink-0 rounded-full bg-accent"
                        title={`Modified: ${activeViewChanges.join(', ')}`}
                        aria-label="Modified"
                        data-attr="workflows-combined-view-modified"
                    />
                )}
            </span>
        </Tooltip>
    )
    return (
        <LemonTabs
            size="small"
            activeKey={activeViewId}
            onChange={(key) => {
                const view = views.find((candidate) => candidate.id === key)
                if (view) {
                    onApplyView(view)
                }
            }}
            data-attr="workflows-combined-views"
            className="[&_[role=tab]]:min-w-0 [&_[role=tab]_div]:min-w-0"
            barClassName="!justify-start gap-x-2 @min-[42rem]/saved-views:gap-x-8 [&>div:first-child]:min-w-0 [&>div:first-child]:!pr-0"
            tabs={visible.map((view) => ({ key: view.id, label: label(view) }))}
            rightSlotClassName="[&&]:mb-0 [&&]:bg-transparent [&&]:pr-0"
            rightSlot={
                overflow.length ? (
                    <LemonMenu
                        items={overflow.map((view) => ({
                            label: label(view),
                            onClick: () => onApplyView(view),
                        }))}
                    >
                        <LemonButton
                            noPadding
                            sideIcon={null}
                            className="!bg-transparent font-normal [--lemon-button-color:var(--color-text-tertiary)] hover:[--lemon-button-color:var(--color-text-primary)] [&_span]:!font-normal [&_span]:!leading-[inherit]"
                            data-attr="workflows-combined-views-more"
                        >
                            <span className="inline-flex items-center gap-0.5">
                                <span>{`More (${overflow.length})`}</span>
                                <IconChevronDown />
                            </span>
                        </LemonButton>
                    </LemonMenu>
                ) : undefined
            }
        />
    )
}
