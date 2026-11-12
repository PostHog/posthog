import { ProfilePicture } from '@posthog/lemon-ui'

import type { _UserApi } from 'products/signals/frontend/generated/api.schemas'

import { EnrichedReviewer } from '../../types'

const MAX_FACES = 3

export function QuillReviewersLine({
    owner,
    claimant,
    reviewers,
}: {
    owner: string
    claimant: _UserApi | null
    reviewers: EnrichedReviewer[]
}): JSX.Element {
    const reviewerFaces = reviewers.filter((reviewer) => reviewer.user && reviewer.user.uuid !== claimant?.uuid)
    const faces = [
        ...(claimant ? [{ key: claimant.uuid, user: claimant }] : []),
        ...reviewerFaces.map((reviewer) => ({ key: reviewer.user!.uuid, user: reviewer.user! })),
    ].slice(0, MAX_FACES)
    const count = `${reviewers.length} suggested ${reviewers.length === 1 ? 'reviewer' : 'reviewers'}`
    return (
        <>
            {faces.length > 0 && (
                <span className="me-1 flex shrink-0 items-center gap-1">
                    {faces.map((face) => (
                        <ProfilePicture key={face.key} user={face.user} size="sm" />
                    ))}
                </span>
            )}
            <span className="truncate">{reviewers.length > 0 ? `${owner} · ${count}` : owner}</span>
        </>
    )
}
