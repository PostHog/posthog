import { useActions } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { FileSystemEntry } from '~/queries/schema/schema-general'

import { workflowFoldersLogic } from './workflowFoldersLogic'

export function WorkflowEmailTemplateActions({ entry, name }: { entry: FileSystemEntry; name: string }): JSX.Element {
    const { moveFileToFolder } = useActions(workflowFoldersLogic)
    const canEdit = !['viewer', 'none'].includes(entry.user_access_level ?? '')
    return (
        <LemonMenu
            items={[
                {
                    label: 'Move to…',
                    onClick: () => moveFileToFolder(entry),
                    disabledReason: canEdit ? undefined : 'Editor access is required',
                },
            ]}
        >
            <LemonButton size="small" icon={<IconEllipsis />} aria-label={`Actions for ${name}`} />
        </LemonMenu>
    )
}
