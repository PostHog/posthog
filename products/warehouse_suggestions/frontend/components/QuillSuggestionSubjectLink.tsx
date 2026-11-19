import { IconExternal } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { subjectUrl } from '../subjectUrl'

export interface QuillSuggestionSubjectLinkProps {
    suggestion: WarehouseSuggestionApi
}

export function QuillSuggestionSubjectLink({ suggestion }: QuillSuggestionSubjectLinkProps): JSX.Element {
    return (
        <Button
            variant="link"
            size="inline"
            className="min-w-0 text-sm font-semibold text-foreground"
            render={<LinkPrimitive to={subjectUrl(suggestion)} target="_blank" />}
        >
            <span className="truncate">{suggestion.payload.subject_name}</span>
            <IconExternal className="shrink-0" />
            <span className="sr-only"> (opens in a new tab)</span>
        </Button>
    )
}
