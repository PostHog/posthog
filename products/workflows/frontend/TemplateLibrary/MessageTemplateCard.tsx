import { IconWebhooks } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { HogFunctionTemplateType } from '~/types'

import { MessageTemplate } from './types'

function FunctionTemplatePreview({
    template,
    hogFunctionTemplate,
}: {
    template: MessageTemplate
    hogFunctionTemplate?: HogFunctionTemplateType
}): JSX.Element {
    const urlInput = template.content.function?.inputs?.url?.value
    const methodInput = template.content.function?.inputs?.method?.value

    return (
        <div className="flex flex-col items-center justify-center gap-2 h-full bg-surface-secondary p-4">
            {hogFunctionTemplate?.icon_url ? (
                <HogFunctionIcon src={hogFunctionTemplate.icon_url} size="large" />
            ) : (
                <IconWebhooks className="text-4xl text-secondary" />
            )}
            <LemonTag>{hogFunctionTemplate?.name ?? template.content.function?.template_id}</LemonTag>
            {typeof urlInput === 'string' && urlInput && (
                <div className="text-xs text-secondary text-center break-all line-clamp-2">
                    {typeof methodInput === 'string' && methodInput ? `${methodInput} ` : ''}
                    {urlInput}
                </div>
            )}
        </div>
    )
}

export function MessageTemplateCard({
    template,
    index,
    onClick,
    actions,
    hogFunctionTemplate,
}: {
    template: MessageTemplate
    index: number
    onClick: () => void
    actions?: React.ReactNode
    hogFunctionTemplate?: HogFunctionTemplateType
}): JSX.Element {
    const emailHtml = template.content?.email?.html
    const isFunctionTemplate = template.type === 'function'

    return (
        <div className="cursor-pointer MessageTemplateItem" onClick={onClick} data-attr="message-template-item">
            <div className="MessageTemplateItemInner border rounded flex flex-col relative overflow-hidden">
                {actions && (
                    <div className="absolute top-2 right-2 z-10" onClick={(e) => e.stopPropagation()}>
                        {actions}
                    </div>
                )}
                <div className="w-full overflow-hidden grow">
                    {isFunctionTemplate ? (
                        <FunctionTemplatePreview template={template} hogFunctionTemplate={hogFunctionTemplate} />
                    ) : emailHtml ? (
                        <iframe
                            srcDoc={emailHtml}
                            sandbox="allow-same-origin"
                            title="Message template preview"
                            className="w-full h-full border-0 bg-white pointer-events-none"
                        />
                    ) : (
                        <FallbackCoverImage src={undefined} alt="cover photo" index={index} className="h-full" />
                    )}
                </div>

                <div className="px-2 py-2 border-t">
                    <h5 className="mb-0.5">{template.name || 'Unnamed template'}</h5>
                    {template.description && (
                        <p className="text-secondary text-xs line-clamp-1 mb-1">{template.description}</p>
                    )}
                    {(template.created_by || template.created_at) && (
                        <div className="flex items-center gap-2 text-xs text-secondary">
                            {template.created_by && <ProfilePicture user={template.created_by} size="sm" showName />}
                            {template.created_by && template.created_at && <span>·</span>}
                            {template.created_at && <TZLabel time={template.created_at} />}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
