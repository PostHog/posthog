import { IconExternal } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { prettifySkillName } from 'products/review_hog/frontend/skillNames'

/** "kept" of "raised" findings, or null when the skill has no findings in the viewer's last Deep reviews. */
export interface SkillKept {
    kept: number
    raised: number
}

function KeptCount({ kept }: { kept: SkillKept | null }): JSX.Element {
    if (kept === null || kept.raised === 0) {
        return <span className="text-xs text-secondary">Not run in your last 10</span>
    }
    return (
        <span className="flex items-center gap-2 text-xs text-secondary">
            <span className="flex h-1.5 w-16 overflow-hidden rounded-sm bg-fill-highlight-100" aria-hidden>
                <span className="h-full bg-success" style={{ width: `${(kept.kept / kept.raised) * 100}%` }} />
            </span>
            <span className="tabular-nums">
                <span className="font-semibold text-default">
                    {kept.kept} of {kept.raised}
                </span>{' '}
                findings kept
            </span>
        </span>
    )
}

/**
 * One review skill: its name, what it does, what it kept in the viewer's own last Deep reviews, and
 * the viewer's control for it. `kept` undefined hides the count, for skills that raise no findings.
 */
export function SkillRow({
    skillName,
    description,
    kept,
    mine,
}: {
    skillName: string
    description: string
    kept?: SkillKept | null
    mine: JSX.Element
}): JSX.Element {
    return (
        <div className="grid grid-cols-1 items-center gap-2 px-4 py-2 @min-[48rem]:grid-cols-[minmax(0,1fr)_minmax(0,16rem)] @min-[48rem]:gap-3">
            <div className="flex min-w-0 flex-col gap-0.5">
                <span className="text-sm font-semibold">{prettifySkillName(skillName)}</span>
                <span className="text-xs text-secondary">{description}</span>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    {kept !== undefined && <KeptCount kept={kept} />}
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
