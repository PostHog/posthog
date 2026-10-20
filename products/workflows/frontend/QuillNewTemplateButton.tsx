import { useActions } from 'kea'

import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { newTemplateAgentLogic } from './TemplateLibrary/newTemplateAgentLogic'

export function QuillNewTemplateButton(): JSX.Element {
    const { startNewTemplate } = useActions(newTemplateAgentLogic)
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <Button data-attr="new-message-button" onClick={startNewTemplate} variant="primary">
                New template
            </Button>
        </AccessControlAction>
    )
}
