import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { PersonSearchMatchFieldEnumApi } from '../generated/api.schemas'

type TagContent = { label: string; explanation: string }

const TAG_BY_FIELD: Record<PersonSearchMatchFieldEnumApi, TagContent> = {
    distinct_id: { label: 'Distinct ID', explanation: "The search matched one of this person's distinct IDs." },
    email: { label: 'Email', explanation: "The search matched this person's email property." },
    name: { label: 'Name', explanation: "The search matched this person's name property." },
    id: { label: 'Person ID', explanation: "The search matched this person's ID." },
}

export function PersonSearchMatchTags({
    matchedFields,
}: {
    matchedFields?: PersonSearchMatchFieldEnumApi[]
}): JSX.Element | null {
    // Skip fields newer than this bundle.
    const tags = (matchedFields ?? []).flatMap((field) => TAG_BY_FIELD[field] ?? [])
    if (tags.length === 0) {
        return null
    }
    return (
        <span className="flex gap-1">
            {tags.map(({ label, explanation }) => (
                <Tooltip key={label} title={explanation}>
                    <LemonTag type="muted" size="small" data-attr="person-search-match-tag">
                        {label}
                    </LemonTag>
                </Tooltip>
            ))}
        </span>
    )
}
