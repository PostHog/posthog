import { hashCodeForString } from 'lib/utils/strings'

import type { ErrorTrackingIssueTagColor } from '~/queries/schema/schema-general'

import { IssueTagColorEnumApi } from '../../generated/api.schemas'

export const ISSUE_TAG_COLORS: ErrorTrackingIssueTagColor[] = Object.values(IssueTagColorEnumApi)

// A tag with no chosen color gets one from its label, not its key, because a new rule has no key until it is saved
// and the rule modal previews the color before that. Renaming such a tag changes its color.
export function issueTagColor(
    label: string,
    color: ErrorTrackingIssueTagColor | null | undefined
): ErrorTrackingIssueTagColor {
    return color ?? ISSUE_TAG_COLORS[hashCodeForString(label) % ISSUE_TAG_COLORS.length]
}
