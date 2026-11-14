import { useValues } from 'kea'

import { IconLetter } from '@posthog/icons'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { getItemId } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { WorkflowFolderPath } from './WorkflowFolderPath'
import { WorkflowFolderRow } from './WorkflowFolderRow'
import { workflowFoldersLogic } from './workflowFoldersLogic'

export function WorkflowEmailTemplateNameCell({ entry, name }: { entry: FileSystemEntry; name: string }): JSX.Element {
    const { pendingFileMoveIds } = useValues(workflowFoldersLogic)
    const canDrag =
        !['viewer', 'none'].includes(entry.user_access_level ?? '') && !pendingFileMoveIds.includes(entry.id)
    return (
        <WorkflowFolderRow
            icon={<IconLetter />}
            drag={canDrag ? { id: getItemId(entry), label: `Drag email template ${name}` } : undefined}
        >
            <WorkflowFolderPath path={entry.path} />
            <LemonTableLink to={urls.workflowsLibraryTemplate(entry.ref ?? '')} title={name} truncateTitle />
        </WorkflowFolderRow>
    )
}
