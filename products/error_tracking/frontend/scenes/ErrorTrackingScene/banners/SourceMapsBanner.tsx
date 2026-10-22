import { useActions } from 'kea'
import posthog from 'posthog-js'
import { ReactNode } from 'react'

import { IconMagicWand } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { WizardHog } from 'scenes/onboarding/shared/wizardHog'

import { BannerCallout } from './BannerCallout'
import { errorTrackingBannersLogic } from './errorTrackingBannersLogic'
import { SourceMapsFixModal } from './SourceMapsFixModal'
import { SOURCE_MAPS_DOCS_URL, sourceMapsFixWizardLogic } from './sourceMapsFixWizardLogic'
import type { SourceMapsRecommendation } from './types'

// Mounts only while the banner is visible, so the "shown" event fires exactly when it was seen.
export function SourceMapsBanner({
    recommendation,
    navigation,
}: {
    recommendation: SourceMapsRecommendation
    navigation?: ReactNode
}): JSX.Element {
    const { openModal } = useActions(sourceMapsFixWizardLogic)
    const { dismissBanner } = useActions(errorTrackingBannersLogic)
    const percent = Math.round((recommendation.meta.unresolved_pct ?? 0) * 100)

    useOnMountEffect(() => {
        posthog.capture('error_tracking_source_maps_banner_shown', {
            unresolved_pct: percent,
            lookback_hours: recommendation.meta.lookback_hours,
        })
    })

    return (
        <>
            <BannerCallout
                illustration={WizardHog}
                title={`${percent}% of your stack traces aren't readable`}
                description="Upload source maps to see your original code. Wizard's setup agent can add the uploads to your build."
                primaryAction={{
                    label: 'Fix with Wizard',
                    icon: <IconMagicWand />,
                    onClick: () => openModal('issues_list'),
                    dataAttr: 'error-tracking-source-maps-banner-wizard',
                }}
                secondaryAction={{
                    label: 'Read docs',
                    to: SOURCE_MAPS_DOCS_URL,
                    targetBlank: true,
                    onClick: () =>
                        posthog.capture('error_tracking_source_maps_docs_clicked', { ui_source: 'issues_list' }),
                    dataAttr: 'error-tracking-source-maps-banner-docs',
                }}
                navigation={navigation}
                onDismiss={() => dismissBanner('source_maps')}
            />
            <SourceMapsFixModal />
        </>
    )
}
