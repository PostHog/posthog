import { IconCheck, IconChevronDown, IconWarning } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { getIssueStatusConfig, StatusIndicator } from '../../components/Indicators'
import { IssueResolvedRule } from '../../components/IssueResolvedRule'
import { IssueStatusSelect } from '../../components/IssueStatusSelect'
import { RESOLVE_MODES } from '../../components/resolveModes'
import type { ErrorTrackingIssueReadApi, ResolvedUntilEnumApi } from '../../generated/api.schemas'

type IssueStatus = ErrorTrackingIssue['status']

const RESOLVED_LABEL_BY_MODE: Record<ResolvedUntilEnumApi, string> = {
    next_occurrence: 'Resolved until the next occurrence',
    new_release: 'Resolved in the next release',
}

function CurrentCheck(): JSX.Element {
    return <IconCheck data-icon="inline-end" className="ms-auto" />
}

export function IssueSceneStatusSelect({
    status,
    resolvedUntil,
    latestRelease,
    stillSeen,
    onChange,
}: {
    status: IssueStatus
    resolvedUntil: ErrorTrackingIssueReadApi['resolved_until'] | undefined
    latestRelease: ErrorTrackingIssueReadApi['latest_release'] | undefined
    stillSeen: boolean
    onChange: (status: IssueStatus, resolvedUntil?: ResolvedUntilEnumApi) => void
}): JSX.Element {
    const showResolveModes = useFeatureFlag('ERROR_TRACKING_RESOLVE_IN_NEXT_RELEASE')
    if (!showResolveModes) {
        return <IssueStatusSelect status={status} onChange={onChange} size="default" />
    }

    // An issue resolved before its mode was recorded reopens on the next exception.
    const currentMode = status === 'resolved' ? (resolvedUntil ?? 'next_occurrence') : null
    const statusLabel = currentMode ? RESOLVED_LABEL_BY_MODE[currentMode] : getIssueStatusConfig(status).label
    const tooltip =
        status === 'resolved' ? (
            <div className="flex flex-col gap-1">
                <IssueResolvedRule resolvedUntil={resolvedUntil} latestRelease={latestRelease} />
                {stillSeen && (
                    <span className="flex gap-1">
                        <IconWarning className="mt-0.5 size-3.5 shrink-0 text-warning-foreground" />
                        Still seen since the resolve. Exceptions keep arriving from releases this issue was already seen
                        in, or older ones, so they don't reopen it.
                    </span>
                )}
            </div>
        ) : null

    const statusItem = (itemStatus: IssueStatus): JSX.Element => (
        <DropdownMenuItem onClick={() => itemStatus !== status && onChange(itemStatus)}>
            <StatusIndicator status={itemStatus} size="xsmall" />
            {itemStatus === status && <CurrentCheck />}
        </DropdownMenuItem>
    )

    return (
        <DropdownMenu>
            <Tooltip disabled={!tooltip}>
                <TooltipTrigger
                    render={
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    variant="outline"
                                    left
                                    className="gap-1"
                                    aria-label={`Status: ${statusLabel}${stillSeen ? ', still seen since the resolve' : ''}`}
                                />
                            }
                        />
                    }
                >
                    <StatusIndicator status={status} size="xsmall" className="text-secondary" />
                    {stillSeen && (
                        <IconWarning
                            className="size-3.5 text-warning-foreground"
                            data-attr="error-tracking-issue-still-seen"
                        />
                    )}
                    <IconChevronDown className="size-3.5 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent>{tooltip}</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="start">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Status</DropdownMenuLabel>
                    {statusItem('active')}
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger data-attr="error-tracking-issue-status-resolved">
                            <StatusIndicator status="resolved" size="xsmall" />
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent>
                            {/* A radio group, so assistive technology announces which mode is current. */}
                            <DropdownMenuRadioGroup
                                value={currentMode ?? ''}
                                onValueChange={(mode: ResolvedUntilEnumApi) =>
                                    mode !== currentMode && onChange('resolved', mode)
                                }
                            >
                                {RESOLVE_MODES.map((mode) => (
                                    <DropdownMenuRadioItem
                                        key={mode.value}
                                        value={mode.value}
                                        closeOnClick
                                        className="h-auto items-start py-1.5"
                                    >
                                        <span className="flex flex-col items-start text-start">
                                            {mode.action}
                                            <Text
                                                size="xs"
                                                variant="muted"
                                                render={<span className="max-w-80 whitespace-normal" />}
                                            >
                                                <IssueResolvedRule
                                                    resolvedUntil={mode.value}
                                                    latestRelease={latestRelease}
                                                />
                                            </Text>
                                        </span>
                                    </DropdownMenuRadioItem>
                                ))}
                            </DropdownMenuRadioGroup>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                    {statusItem('suppressed')}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
