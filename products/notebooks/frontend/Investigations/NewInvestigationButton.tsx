import { useActions, useValues } from 'kea'

import { LemonButton, LemonMenu } from '@posthog/lemon-ui'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { InvestigationStarter, investigationCreationLogic } from './investigationCreationLogic'

const STARTERS: { key: InvestigationStarter; label: string }[] = [
    { key: 'blank', label: 'Blank investigation' },
    { key: 'conversion', label: 'Investigate a conversion change' },
    { key: 'example', label: 'Explore a worked example' },
]

export function NewInvestigationButton(): JSX.Element {
    const { createdNotebookLoading } = useValues(investigationCreationLogic)
    const { createInvestigation } = useActions(investigationCreationLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav) {
        return (
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={<Button disabled={createdNotebookLoading} data-attr="new-investigation" />}
                >
                    {createdNotebookLoading ? 'Creating investigation…' : 'New investigation'}
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                    {STARTERS.map(({ key, label }) => (
                        <DropdownMenuItem
                            key={key}
                            disabled={createdNotebookLoading}
                            onClick={() => createInvestigation(key)}
                        >
                            {label}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuContent>
            </DropdownMenu>
        )
    }
    return (
        <LemonMenu
            items={STARTERS.map(({ key, label }) => ({
                label,
                onClick: () => createInvestigation(key),
                disabledReason: createdNotebookLoading ? 'Creating your investigation.' : undefined,
            }))}
        >
            <LemonButton type="secondary" size="small" loading={createdNotebookLoading} data-attr="new-investigation">
                New investigation
            </LemonButton>
        </LemonMenu>
    )
}
