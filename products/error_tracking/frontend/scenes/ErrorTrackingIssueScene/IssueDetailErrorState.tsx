import { IconRefresh, IconWarning } from '@posthog/icons'

import { Button, Heading, Text } from 'lib/ui/quill'

export interface IssueDetailErrorStateProps {
    loading: boolean
    onRetry: () => void
}

export function IssueDetailErrorState({ loading, onRetry }: IssueDetailErrorStateProps): JSX.Element {
    return (
        <div className="flex min-h-64 flex-1 items-center justify-center px-4 py-8 text-center">
            <div className="flex max-w-md flex-col items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-full bg-fill-secondary text-secondary">
                    <IconWarning className="size-5" />
                </div>
                <div className="flex flex-col gap-1">
                    <Heading size="base">Couldn't load this exception</Heading>
                    <Text size="sm" variant="muted">
                        The query for it failed. Try again, or pick another exception from the list.
                    </Text>
                </div>
                <Button variant="outline" loading={loading} onClick={onRetry} data-attr="issue-detail-retry">
                    <IconRefresh />
                    Try again
                </Button>
            </div>
        </div>
    )
}
