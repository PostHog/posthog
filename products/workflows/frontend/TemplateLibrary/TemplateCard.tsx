import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { UserBasicType } from '~/types'

export function TemplateCard({
    name,
    description,
    createdBy,
    createdAt,
    preview,
    tags,
    onClick,
    actions,
    'data-attr': dataAttr,
}: {
    name: string
    description?: string
    createdBy?: UserBasicType | null
    createdAt?: string | null
    /** Fills the card above the footer: an email preview, a destination summary, a cover image. */
    preview: React.ReactNode
    tags?: React.ReactNode
    onClick: () => void
    actions?: React.ReactNode
    'data-attr': string
}): JSX.Element {
    return (
        <div className="cursor-pointer MessageTemplateItem" onClick={onClick} data-attr={dataAttr}>
            <div className="MessageTemplateItemInner border rounded flex flex-col relative overflow-hidden">
                {actions && (
                    <div className="absolute top-2 right-2 z-10" onClick={(e) => e.stopPropagation()}>
                        {actions}
                    </div>
                )}
                <div className="w-full overflow-hidden grow">{preview}</div>

                <div className="px-2 py-2 border-t">
                    <h5 className="mb-0.5">{name || 'Unnamed template'}</h5>
                    {description && <p className="text-secondary text-xs line-clamp-1 mb-1">{description}</p>}
                    {tags && <div className="flex gap-1 flex-wrap mb-1">{tags}</div>}
                    {(createdBy || createdAt) && (
                        <div className="flex items-center gap-2 text-xs text-secondary">
                            {createdBy && <ProfilePicture user={createdBy} size="sm" showName />}
                            {createdBy && createdAt && <span>·</span>}
                            {createdAt && <TZLabel time={createdAt} />}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
