import { Link, Tooltip } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { prettifySkillName } from 'products/review_hog/frontend/skillNames'

/** "kept" of "raised" findings, or null when the skill has no findings in the viewer's last Deep reviews. */
export interface SkillKept {
    kept: number
    raised: number
}

function KeptCount({ kept }: { kept: SkillKept | null }): JSX.Element {
    if (kept === null || kept.raised === 0) {
        return <span className="text-xs text-secondary">No findings in your last 10</span>
    }
    return (
        <span className="flex items-center gap-2 text-xs text-secondary">
            <span className="flex h-1.5 w-16 overflow-hidden rounded-sm bg-fill-highlight-100" aria-hidden>
                <span className="h-full bg-success" style={{ width: `${(kept.kept / kept.raised) * 100}%` }} />
            </span>
            <span className="tabular-nums">
                <span className="font-semibold text-default">{`${kept.kept} of ${kept.raised}`}</span> findings kept
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
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-2">
            <div className="flex min-w-48 flex-1 flex-col gap-0.5">
                <span className="text-sm font-semibold">{prettifySkillName(skillName)}</span>
                <Tooltip title={description}>
                    {/* Focusable, so a keyboard user can open the tooltip that holds the clipped text. */}
                    <span tabIndex={0} className="line-clamp-1 text-xs text-secondary">
                        {description}
                    </span>
                </Tooltip>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    {kept !== undefined && <KeptCount kept={kept} />}
                    <Tooltip title="Changes the skill for everyone in the project">
                        <Link
                            to={urls.skill(skillName)}
                            target="_blank"
                            className="text-xs"
                            data-attr="review-hog-edit-skill-text"
                        >
                            Edit skill
                        </Link>
                    </Tooltip>
                </div>
            </div>
            <div className="flex max-w-full min-w-0 items-center">{mine}</div>
        </div>
    )
}
