import { useValues } from 'kea'

import { Avatar, AvatarFallback, Card, CardContent, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { releaseLogic } from './releaseLogic'
import { ReleaseOwnerPicker } from './ReleaseOwnerPicker'
import { ReleaseRow } from './releaseUtils'

function DetailRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex min-h-7 items-center justify-between gap-3 @md:justify-start @md:gap-2">
            <Text size="xs" variant="muted">
                {label}
            </Text>
            <div className="flex min-w-0 items-center gap-1.5">{children}</div>
        </div>
    )
}

export function ReleaseDetailsCard({ row }: { row: ReleaseRow }): JSX.Element {
    const { canEditReleases } = useValues(releaseLogic)

    return (
        <Card size="sm" className="@container" data-attr="release-details">
            <CardContent className="flex flex-col gap-1 @md:flex-row @md:flex-wrap @md:items-center @md:gap-x-8">
                <DetailRow label="Owner">
                    {canEditReleases ? (
                        <ReleaseOwnerPicker row={row} />
                    ) : row.owner ? (
                        <>
                            <Avatar size="xs">
                                <AvatarFallback>{row.owner.first_name.charAt(0).toUpperCase()}</AvatarFallback>
                            </Avatar>
                            <Text size="xs" className="truncate">
                                {row.owner.first_name}
                            </Text>
                        </>
                    ) : (
                        <Text size="xs" variant="muted">
                            No owner
                        </Text>
                    )}
                </DetailRow>
                <DetailRow label="Created">
                    <Text size="xs" render={<span />}>
                        <TZLabel time={row.createdAt} formatDate="D MMM YYYY" formatTime="" />
                    </Text>
                </DetailRow>
            </CardContent>
        </Card>
    )
}
