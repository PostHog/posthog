import { useActions, useValues } from 'kea'

import { LemonButton, LemonMenu } from '@posthog/lemon-ui'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { InvestigationStarter, investigationCreationLogic } from './investigationCreationLogic'

const STARTERS: { key: InvestigationStarter; label: string }[] = [
    { key: 'blank', label: 'Blank investigation' },
    { key: 'conversion', label: 'Investigate a conversion change' },
    { key: 'example', label: 'Explore a worked example' },
]

export function NewInvestigationButton(): JSX.Element {
    const { createdInvestigationLoading } = useValues(investigationCreationLogic)
    const { createInvestigation } = useActions(investigationCreationLogic)
    const accessReason = getAccessControlDisabledReason(
        AccessControlResourceType.Investigation,
        AccessControlLevel.Editor
    )
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav) {
        return (
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            disabled={createdInvestigationLoading || !!accessReason}
                            data-attr="new-investigation"
                        />
                    }
                >
                    {createdInvestigationLoading ? 'Creating investigation…' : 'New investigation'}
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                    {STARTERS.map(({ key, label }) => (
                        <DropdownMenuItem
                            key={key}
                            disabled={createdInvestigationLoading || !!accessReason}
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
                disabledReason:
                    accessReason ?? (createdInvestigationLoading ? 'Creating your investigation.' : undefined),
            }))}
        >
            <LemonButton
                disabledReason={accessReason}
                type="primary"
                loading={createdInvestigationLoading}
                data-attr="new-investigation"
            >
                New investigation
            </LemonButton>
        </LemonMenu>
    )
}
