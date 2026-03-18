import { LemonTag } from '@posthog/lemon-ui'

interface IssueTaggable {
    abandonment: boolean
    confusion: boolean
    exception: string | null
}

export function getIssueTags(event: IssueTaggable): JSX.Element[] {
    const tags: JSX.Element[] = []
    if (event.exception) {
        tags.push(
            <LemonTag key="exception" size="medium" type="option">
                {event.exception === 'blocking' ? 'blocking error' : 'non-blocking error'}
            </LemonTag>
        )
    }
    if (event.abandonment) {
        tags.push(
            <LemonTag key="abandonment" size="medium" type="option">
                abandoned
            </LemonTag>
        )
    }
    if (event.confusion) {
        tags.push(
            <LemonTag key="confusion" size="medium" type="option">
                confusion
            </LemonTag>
        )
    }
    return tags
}
