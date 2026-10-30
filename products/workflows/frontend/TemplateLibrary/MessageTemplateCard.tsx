import { LemonTag } from '@posthog/lemon-ui'

import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { MessageTemplate } from './types'

export function MessageTemplateCard({
    template,
    index,
    onClick,
    actions,
    onTagClick,
}: {
    template: MessageTemplate
    index: number
    onClick: () => void
    actions?: React.ReactNode
    onTagClick?: (tag: string) => void
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
                            title="Message template preview"
                            className="w-full h-full border-0 bg-white pointer-events-none"
                        />
                    ) : (
                        <FallbackCoverImage src={undefined} alt="cover photo" index={index} className="h-full" />
                    )}
                </div>

                <div className="px-2 py-2 border-t">
                    <div className="flex items-center gap-1 mb-0.5">
                        <h5 className="mb-0 truncate">{template.name || 'Unnamed template'}</h5>
                        {template.transactional_hog_flow_id && (
                            <LemonTag type="success" size="small">
                                Transactional
                            </LemonTag>
                        )}
                    </div>
                    {template.description && (
                        <p className="text-secondary text-xs line-clamp-1 mb-1">{template.description}</p>
                    )}
                    {!!template.tags?.length && (
                        <div className="mb-1" onClick={(e) => e.stopPropagation()}>
                            <ObjectTags
                                tags={[...template.tags]}
                                staticOnly
                                onTagClick={onTagClick}
                                maxVisibleTags={3}
                                data-attr="message-template-tags"
                            />
                        </div>
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
