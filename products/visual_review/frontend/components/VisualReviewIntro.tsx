import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'

import { ProductKey } from '~/queries/schema/schema-general'

// Where to learn what Visual review is. The product is alpha and has no public
// docs page yet, so point at the in-repo README — the canonical explainer.
const VISUAL_REVIEW_DOCS_URL = 'https://github.com/PostHog/posthog/blob/master/products/visual_review/README.md'

// First-landing orientation for Visual review. People often arrive on a run
// page straight from a GitHub link with no idea where they are, so this gives
// the page a product identity and a one-line "what is this" with a docs link.
// Dismissible and remembered per user via `has_seen_product_intro_for`.
export function VisualReviewIntro({
    isEmpty = false,
    actionElementOverride,
}: {
    isEmpty?: boolean
    actionElementOverride?: JSX.Element
}): JSX.Element | null {
    return (
        <ProductIntroduction
            productName="Visual review"
            productKey={ProductKey.VISUAL_REVIEW}
            thingName="visual review repo"
            description="Visual regression testing that keeps baselines in git. CI captures screenshots, PostHog diffs them against committed baselines, and you review and approve changes here."
            secondaryDescription="Review and approve the visual changes a CI run found, then finalize to commit the updated baselines back to the PR."
            docsURL={VISUAL_REVIEW_DOCS_URL}
            isEmpty={isEmpty}
            actionElementOverride={actionElementOverride}
            className="my-0"
        />
    )
}
