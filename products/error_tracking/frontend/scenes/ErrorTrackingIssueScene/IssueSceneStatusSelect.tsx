import { IconCheck, IconChevronDown } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/quill'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { getIssueStatusConfig, StatusIndicator } from '../../components/Indicators'
import { IssueResolvedRule } from '../../components/IssueResolvedRule'
import { IssueStatusSelect } from '../../components/IssueStatusSelect'
import { RESOLVE_MODES } from '../../components/resolveModes'
import type { ErrorTrackingIssueReadApi, ResolvedUntilEnumApi } from '../../generated/api.schemas'

type IssueStatus = ErrorTrackingIssue['status']

function CurrentCheck(): JSX.Element {
    return <IconCheck data-icon="inline-end" className="ms-auto" />
}

export function IssueSceneStatusSelect({
    status,
    resolvedUntil,
    latestRelease,
    onChange,
}: {
    status: IssueStatus
    resolvedUntil: ErrorTrackingIssueReadApi['resolved_until'] | undefined
    latestRelease: ErrorTrackingIssueReadApi['latest_release'] | undefined
    onChange: (status: IssueStatus, resolvedUntil?: ResolvedUntilEnumApi) => void
}): JSX.Element {
    const showResolveModes = useFeatureFlag('ERROR_TRACKING_RESOLVE_IN_NEXT_RELEASE')
    if (!showResolveModes) {
        return <IssueStatusSelect status={status} onChange={onChange} size="default" />
    }

    // An issue resolved before its mode was recorded reopens on the next exception.
    const currentMode = status === 'resolved' ? (resolvedUntil ?? 'next_occurrence') : null

    const statusItem = (itemStatus: IssueStatus): JSX.Element => (
        <DropdownMenuItem onClick={() => itemStatus !== status && onChange(itemStatus)}>
            <StatusIndicator status={itemStatus} size="xsmall" />
            {itemStatus === status && <CurrentCheck />}
        </DropdownMenuItem>
    )

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        left
                        className="gap-1"
                        aria-label={`Status: ${getIssueStatusConfig(status).label}`}
                    />
                }
            >
                <StatusIndicator
                    status={status}
                    size="xsmall"
                    className="text-secondary"
                    tooltip={
                        status === 'resolved' ? (
                            <IssueResolvedRule resolvedUntil={resolvedUntil} latestRelease={latestRelease} />
                        ) : undefined
                    }
                />
                <IconChevronDown className="size-3.5 text-muted-foreground" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Status</DropdownMenuLabel>
                    {statusItem('active')}
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger data-attr="error-tracking-issue-status-resolved">
                            <StatusIndicator status="resolved" size="xsmall" />
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            {RESOLVE_MODES.map((mode) => (
                                <DropdownMenuItem
                                    key={mode.value}
                                    description={
                                        <IssueResolvedRule resolvedUntil={mode.value} latestRelease={latestRelease} />
                                    }
                                    onClick={() => mode.value !== currentMode && onChange('resolved', mode.value)}
                                >
                                    {mode.action}
                                    {mode.value === currentMode && <CurrentCheck />}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                    {statusItem('suppressed')}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
