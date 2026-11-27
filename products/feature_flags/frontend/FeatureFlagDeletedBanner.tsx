import { ReactNode } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { FeatureFlagType } from '~/types'

import { deletedCohortDisabledReason, deletedCohortFilters, restoreChecksCohorts } from './deletedCohortFilters'
import { RESTORE_UNAVAILABLE_DISABLED_REASON, canRestoreFeatureFlag } from './featureFlagConfigFormat'

export interface FeatureFlagDeletedBannerProps {
    /** The flag as the flag API returns it. That response sets `can_edit` and marks conditions on deleted cohorts. */
    flag: Pick<FeatureFlagType, 'deleted' | 'archived' | 'can_edit' | 'filters'>
    onRestore: () => void
    restoreLoading: boolean
    /** How the first sentence names the flag. */
    subject?: ReactNode
    /** Tells apart the pages that people restore from. */
    restoreDataAttr?: string
    className?: string
    /** Lines that the page adds after the explanation. */
    children?: ReactNode
}

/** Explains that a flag is deleted, and offers a restore to people who can edit the flag. */
export function FeatureFlagDeletedBanner({
    flag,
    onRestore,
    restoreLoading,
    subject = 'This feature flag',
    restoreDataAttr = 'restore-feature-flag-banner',
    className,
    children,
}: FeatureFlagDeletedBannerProps): JSX.Element | null {
    if (!flag.deleted) {
        return null
    }

    const canRestore = canRestoreFeatureFlag(flag.filters)
    // The flag API refuses the restore while a release condition targets a deleted cohort.
    const restoreBlockedReason = restoreChecksCohorts(flag)
        ? deletedCohortDisabledReason(deletedCohortFilters(flag.filters))
        : undefined

    return (
        <LemonBanner
            type="error"
            className={className}
            action={
                flag.can_edit && canRestore
                    ? {
                          children: 'Restore',
                          onClick: onRestore,
                          loading: restoreLoading,
                          disabledReason: restoreBlockedReason,
                          'data-attr': restoreDataAttr,
                      }
                    : undefined
            }
        >
            {subject} is deleted. It's hidden from the flag list and can't be evaluated.{' '}
            {!canRestore
                ? RESTORE_UNAVAILABLE_DISABLED_REASON
                : flag.can_edit
                  ? 'Restore it to use it again.'
                  : 'Ask someone with edit access to restore it.'}
            {children}
        </LemonBanner>
    )
}
