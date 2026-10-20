import { Button } from '@posthog/quill'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { suggestedTestAccountFilterUrl } from 'scenes/settings/environment/suggestedTestAccountFilter'
import { urls } from 'scenes/urls'

import type { AnyPropertyFilter } from '~/types'

import type { InsightDataCheckFilterApi } from 'products/product_analytics/frontend/generated/api.schemas'

export function FilterSettingsButton({
    rule,
    children,
}: {
    rule: InsightDataCheckFilterApi | null
    children: React.ReactNode
}): JSX.Element {
    // The new tab opens the project this insight belongs to, even if another tab has switched projects since.
    const href = addProjectIdIfMissing(
        rule
            ? suggestedTestAccountFilterUrl(rule as unknown as AnyPropertyFilter)
            : urls.settings('environment-customization', 'internal-user-filtering')
    )
    return (
        <Button
            variant="outline"
            size="sm"
            className="no-underline"
            render={
                // Lemon's Link adds its own link styles over the button's, so a plain anchor opens the settings.
                // eslint-disable-next-line react/forbid-elements
                <a href={href} target="_blank" rel="noopener noreferrer" />
            }
            data-attr="insight-data-check-filter-settings"
        >
            {children}
        </Button>
    )
}
