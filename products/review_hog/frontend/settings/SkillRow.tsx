import { IconExternal } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { prettifySkillName } from 'products/review_hog/frontend/skillNames'

/** One review skill: its name, what it does, and the viewer's control for it. */
export function SkillRow({
    skillName,
    description,
    mine,
}: {
    skillName: string
    description: string
    mine: JSX.Element
}): JSX.Element {
    return (
        <div className="grid grid-cols-1 items-center gap-2 px-4 py-2 @min-[48rem]:grid-cols-[minmax(0,1fr)_minmax(0,16rem)] @min-[48rem]:gap-3">
            <div className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-semibold">{prettifySkillName(skillName)}</span>
                <span className="text-xs text-secondary">{description}</span>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <Link
                        to={urls.skill(skillName)}
                        target="_blank"
                        className="inline-flex items-center gap-0.5 text-xs"
                        data-attr="review-hog-edit-skill-text"
                    >
                        Edit text for the project <IconExternal className="size-3" />
                    </Link>
                </div>
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-1">
                <span className="text-xs text-secondary @min-[48rem]:hidden">Mine:</span>
                {mine}
            </div>
        </div>
    )
}
