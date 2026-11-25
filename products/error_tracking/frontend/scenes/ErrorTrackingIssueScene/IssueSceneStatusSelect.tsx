import {
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from 'lib/ui/quill'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { getIssueStatusConfig, StatusIndicator } from '../../components/Indicators'
import { IssueResolvedRule } from '../../components/IssueResolvedRule'
import { RESOLVE_MODES } from '../../components/resolveModes'
import type { ErrorTrackingIssueReadApi, ResolvedUntilEnumApi } from '../../generated/api.schemas'

type IssueStatus = ErrorTrackingIssue['status']

// The value of a resolved option names its mode too, so the two resolved options stay apart.
const resolvedOptionValue = (mode: ResolvedUntilEnumApi): string => `resolved:${mode}`

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
    const value =
        status === 'resolved'
            ? resolvedOptionValue(resolvedUntil === 'new_release' ? 'new_release' : 'next_occurrence')
            : status

    return (
        <Select
            value={value}
            onValueChange={(nextValue: string | null) => {
                if (!nextValue || nextValue === value) {
                    return
                }
                const mode = RESOLVE_MODES.find((option) => resolvedOptionValue(option.value) === nextValue)
                if (mode) {
                    onChange('resolved', mode.value)
                } else {
                    onChange(nextValue as IssueStatus)
                }
            }}
        >
            <SelectTrigger
                size="default"
                className="gap-1"
                aria-label={`Status: ${getIssueStatusConfig(status).label}`}
            >
                <SelectValue>
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
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                <SelectGroup>
                    <SelectGroupLabel className="py-1">Status</SelectGroupLabel>
                    <SelectItem value="active">
                        <StatusIndicator status="active" size="xsmall" />
                    </SelectItem>
                    {RESOLVE_MODES.map((mode) => (
                        <SelectItem key={mode.value} value={resolvedOptionValue(mode.value)} className="h-auto">
                            <Item size="xs" className="p-0">
                                <ItemContent variant="menuItem">
                                    <ItemTitle>
                                        <StatusIndicator status="resolved" size="xsmall" />
                                    </ItemTitle>
                                    <ItemDescription className="max-w-80 line-clamp-none whitespace-normal">
                                        <IssueResolvedRule resolvedUntil={mode.value} latestRelease={latestRelease} />
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        </SelectItem>
                    ))}
                    <SelectItem value="suppressed">
                        <StatusIndicator status="suppressed" size="xsmall" />
                    </SelectItem>
                </SelectGroup>
            </SelectContent>
        </Select>
    )
}
