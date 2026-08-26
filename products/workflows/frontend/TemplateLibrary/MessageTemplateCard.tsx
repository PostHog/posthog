import { IconWebhooks } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import { HogFunctionIcon } from 'scenes/hog-functions/configuration/HogFunctionIcon'

import { HogFunctionTemplateType } from '~/types'

import { TemplateCard } from './TemplateCard'
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
        <TemplateCard
            name={template.name}
            description={template.description}
            createdBy={template.created_by}
            createdAt={template.created_at}
            onClick={onClick}
            actions={actions}
            data-attr="message-template-item"
            preview={
                isFunctionTemplate ? (
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
                )
            }
        />
    )
}
