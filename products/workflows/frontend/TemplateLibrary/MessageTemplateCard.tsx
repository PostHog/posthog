import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { MessageTemplate } from './messageTemplatesLogic'

export function MessageTemplateCard({
    template,
    index,
    onClick,
    actions,
}: {
    template: MessageTemplate
    index: number
    onClick: () => void
    actions?: React.ReactNode
}): JSX.Element {
    const emailHtml = template.content?.email?.html

    return (
        <div className="cursor-pointer MessageTemplateItem" onClick={onClick} data-attr="message-template-item">
            <div className="MessageTemplateItemInner border rounded flex flex-col relative overflow-hidden">
                {actions && (
                    <div className="absolute top-2 right-2 z-10" onClick={(e) => e.stopPropagation()}>
                        {actions}
                    </div>
                )}
                <div className="w-full overflow-hidden grow">
                    {emailHtml ? (
                        <iframe
                            srcDoc={emailHtml}
                            sandbox="allow-same-origin"
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
