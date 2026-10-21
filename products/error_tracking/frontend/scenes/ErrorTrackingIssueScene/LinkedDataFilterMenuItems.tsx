import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconLive, IconRewindPlay } from '@posthog/icons'

import { DropdownMenuCheckboxItem, DropdownMenuGroup, DropdownMenuLabel } from 'lib/ui/quill'

import type { ErrorTrackingLinkedDataKind } from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { issueLinkedDataLogic } from './issueLinkedDataLogic'
import { LINKED_DATA_FILTER_LABELS } from './linkedDataFilterLabels'

const ICONS: Record<ErrorTrackingLinkedDataKind, ReactNode> = {
    recording: <IconRewindPlay />,
    logs: <IconLive />,
}

export function LinkedDataFilterMenuItems(): JSX.Element {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const { linkedDataKinds, requiredLinks } = useValues(issueLinkedDataLogic({ issueId }))
    const { setLinkRequired } = useActions(issueLinkedDataLogic({ issueId }))

    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>Linked data</DropdownMenuLabel>
            {linkedDataKinds.map((kind) => (
                <DropdownMenuCheckboxItem
                    key={kind}
                    checked={requiredLinks.includes(kind)}
                    closeOnClick
                    onCheckedChange={(checked) => setLinkRequired(kind, checked)}
                    data-attr={`error-tracking-issue-filter-with-${kind}`}
                >
                    {ICONS[kind]}
                    {LINKED_DATA_FILTER_LABELS[kind]}
                </DropdownMenuCheckboxItem>
            ))}
        </DropdownMenuGroup>
    )
}
