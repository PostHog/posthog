import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheckCircle, IconXCircle } from '@posthog/icons'
import { DropdownMenuItem, Spinner } from '@posthog/quill-primitives'

import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { todayMenuLinkItem } from '~/layout/today/todayMenuLinkItem'

import type { WizardRunApi } from '../../generated/api.schemas'
import { wizardRunIsActive } from '../../lib/wizardRunDisplay'
import { wizardRunSyncLogic } from '../../logics/wizardRunSyncLogic'
import { wizardRunSidebarLogic } from './wizardRunSidebarLogic'

function RunCount({ count, label, icon }: { count: number; label: string; icon: JSX.Element }): JSX.Element | null {
    if (count === 0) {
        return null
    }
    return (
        <span className="flex items-center gap-1" title={`${count} ${label}`}>
            {icon}
            <span translate="no">{count}</span>
            <span className="sr-only">{label}</span>
        </span>
    )
}

function RunCounts({ runs }: { runs: WizardRunApi[] }): JSX.Element {
    const running = runs.filter(wizardRunIsActive).length
    const failed = runs.filter((run) => run.status === 'failed').length
    const completed = runs.filter((run) => run.status === 'completed').length
    if (running + failed + completed === 0) {
        return <span>No recent runs</span>
    }
    return (
        <span className="flex items-center gap-2">
            <RunCount count={running} label="running" icon={<Spinner className="size-3" />} />
            <RunCount
                count={failed}
                label="failed"
                icon={<IconXCircle className="size-3 text-destructive-foreground" />}
            />
            <RunCount
                count={completed}
                label="completed"
                icon={<IconCheckCircle className="size-3 text-success-foreground" />}
            />
        </span>
    )
}

export function WizardRunsMoreMenuItem({ projectId }: { projectId: string }): JSX.Element {
    const { userRuns } = useValues(wizardRunSyncLogic({ projectId }))
    const { user } = useValues(userLogic)
    const { clickState, markRunsSeen } = useActions(wizardRunSidebarLogic({ projectId, userId: user?.id ?? 0 }))

    // The item renders only while the More menu is open, so mounting it means the user saw the runs.
    useEffect(() => {
        markRunsSeen()
    }, [markRunsSeen])

    return (
        <DropdownMenuItem
            render={todayMenuLinkItem(urls.wizardRuns())}
            description={
                <span className="flex flex-col gap-1">
                    <span>The Wizard is a setup agent that automatically installs PostHog for you</span>
                    <RunCounts runs={userRuns} />
                </span>
            }
            onClick={() => clickState('today_more_menu')}
            data-attr="more-menu-wizard-runs-button"
        >
            Wizard
        </DropdownMenuItem>
    )
}
