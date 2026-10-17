import { IconCode } from '@posthog/icons'
import { LemonTag, LemonTagProps, Tooltip } from '@posthog/lemon-ui'

import { isCodeManagedTemplate } from './codeManagedTemplate'
import { MessageTemplate } from './types'

export function CodeManagedTag({
    template,
    size,
}: {
    template: Pick<MessageTemplate, 'managed_by'> | null | undefined
    size?: LemonTagProps['size']
}): JSX.Element | null {
    if (!isCodeManagedTemplate(template)) {
        return null
    }

    return (
        <Tooltip title="This template is uploaded from a file in a repository. To change it, edit the file and upload it again.">
            <LemonTag type="default" size={size} icon={<IconCode />} data-attr="message-template-managed-by-code">
                Managed by code
            </LemonTag>
        </Tooltip>
    )
}
