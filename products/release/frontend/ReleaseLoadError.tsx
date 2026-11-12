import { useActions } from 'kea'

import { IconFlag } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { releaseLogic } from './releaseLogic'

export function ReleaseLoadError({ title }: { title: string }): JSX.Element {
    const { reload } = useActions(releaseLogic)
    return (
        <div data-quill>
            <Empty>
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconFlag />
                    </EmptyMedia>
                    <EmptyTitle>{title}</EmptyTitle>
                    <EmptyDescription>Check your connection, then try again.</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" onClick={() => reload(true)} data-attr="release-retry">
                        Try again
                    </Button>
                </EmptyContent>
            </Empty>
        </div>
    )
}
