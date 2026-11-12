import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconFlag } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Spinner,
} from '@posthog/quill'

import { releaseImportLogic } from './releaseImportLogic'

export function ReleaseAutoImport(): JSX.Element {
    const { autoImportState } = useValues(releaseImportLogic)
    const { runAutoImport } = useActions(releaseImportLogic)

    useEffect(() => {
        if (autoImportState === 'idle') {
            runAutoImport()
        }
    }, [autoImportState, runAutoImport])

    if (autoImportState === 'failed') {
        return (
            <Empty data-attr="release-auto-import-failed">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconFlag />
                    </EmptyMedia>
                    <EmptyTitle>Your releases could not be set up</EmptyTitle>
                    <EmptyDescription>Check your connection, then try again.</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" onClick={runAutoImport} data-attr="release-auto-import-retry">
                        Try again
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }
    return (
        <Empty data-attr="release-auto-import">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <Spinner />
                </EmptyMedia>
                <EmptyTitle>Setting up your releases</EmptyTitle>
                <EmptyDescription>
                    Creating a release for each active feature flag. Experiments and early access features show inside
                    the release of their flag. This takes a few seconds.
                </EmptyDescription>
            </EmptyHeader>
        </Empty>
    )
}
