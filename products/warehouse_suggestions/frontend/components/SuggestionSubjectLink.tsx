import { Link } from '@posthog/lemon-ui'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { subjectUrl } from '../subjectUrl'

export interface SuggestionSubjectLinkProps {
    suggestion: WarehouseSuggestionApi
}

export function SuggestionSubjectLink({ suggestion }: SuggestionSubjectLinkProps): JSX.Element {
    return (
        <Link
            to={subjectUrl(suggestion)}
            target="_blank"
            targetBlankIcon
            subtle
            className="inline-flex min-w-0 items-center gap-1 text-sm font-semibold"
        >
            <span className="truncate">{suggestion.payload.subject_name}</span>
            <span className="sr-only"> (opens in a new tab)</span>
        </Link>
    )
}
