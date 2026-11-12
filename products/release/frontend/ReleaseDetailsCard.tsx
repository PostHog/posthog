import { useActions, useValues } from 'kea'

import { Avatar, AvatarFallback, Button, Card, CardContent, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { releaseLogic } from './releaseLogic'
import { ReleaseRow } from './releaseUtils'

function DetailRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex min-h-7 items-center justify-between gap-3">
            <Text size="xs" variant="muted">
                {label}
            </Text>
            <div className="flex min-w-0 items-center gap-1.5">{children}</div>
        </div>
    )
}

export function ReleaseDetailsCard({ row }: { row: ReleaseRow }): JSX.Element {
    const { user, canEditReleases } = useValues(releaseLogic)
    const { updateRelease } = useActions(releaseLogic)

    return (
        <Card size="sm" data-attr="release-details">
            <CardContent className="flex flex-col gap-1">
                <DetailRow label="Owner">
                    {row.owner ? (
                        <>
                            <Avatar size="xs">
                                <AvatarFallback>{row.owner.first_name.charAt(0).toUpperCase()}</AvatarFallback>
                            </Avatar>
                            <Text size="xs" className="truncate">
                                {row.owner.first_name}
                            </Text>
                        </>
                    ) : !canEditReleases ? (
                        <Text size="xs" variant="muted">
                            No owner
                        </Text>
                    ) : (
                        <Button
                            size="sm"
                            variant="outline"
                            data-attr="release-assign"
                            onClick={() => updateRelease(row.id, { owner_id: user?.id ?? null })}
                        >
                            Assign to me
                        </Button>
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
