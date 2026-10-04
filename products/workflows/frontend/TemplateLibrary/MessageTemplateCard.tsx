import { FallbackCoverImage } from 'lib/components/FallbackCoverImage/FallbackCoverImage'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { MinimalHedgehogConfig } from '~/types'

import { MessageTemplateListItem } from './types'

function isMinimalHedgehogConfig(value: unknown): value is MinimalHedgehogConfig {
    if (!value || typeof value !== 'object') {
        return false
    }
    const config = value as Record<string, unknown>
    return (
        typeof config.use_as_profile === 'boolean' &&
        (typeof config.color === 'string' || config.color === null) &&
        (typeof config.skin === 'string' || config.skin === null) &&
        Array.isArray(config.accessories) &&
        config.accessories.every((accessory) => typeof accessory === 'string')
    )
}

export function MessageTemplateCard({
    template,
    index,
    onClick,
    actions,
}: {
    template: MessageTemplateListItem
    index: number
    onClick: () => void
    actions?: React.ReactNode
}): JSX.Element {
    const emailHtml = template.content?.email?.html
    const createdBy = template.created_by
        ? {
              first_name: template.created_by.first_name,
              last_name: template.created_by.last_name,
              email: template.created_by.email,
              hedgehog_config: isMinimalHedgehogConfig(template.created_by.hedgehog_config)
                  ? template.created_by.hedgehog_config
                  : undefined,
          }
        : null

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
                    <h5 className="mb-0.5">{template.name || 'Unnamed template'}</h5>
                    {template.description && (
                        <p className="text-secondary text-xs line-clamp-1 mb-1">{template.description}</p>
                    )}
                    {(createdBy || template.created_at) && (
                        <div className="flex items-center gap-2 text-xs text-secondary">
                            {createdBy && <ProfilePicture user={createdBy} size="sm" showName />}
                            {createdBy && template.created_at && <span>·</span>}
                            {template.created_at && <TZLabel time={template.created_at} />}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
