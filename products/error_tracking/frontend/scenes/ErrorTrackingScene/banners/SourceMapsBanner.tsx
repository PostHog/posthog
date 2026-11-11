import { useActions } from 'kea'
import posthog from 'posthog-js'
import { ReactNode } from 'react'

import { IconMagicWand } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Link } from 'lib/lemon-ui/Link'
import { WizardHog } from 'scenes/onboarding/shared/wizardHog'

import { BannerCallout } from './BannerCallout'
import { errorTrackingBannersLogic } from './errorTrackingBannersLogic'
import { sourceMapsExamplesLogic } from './sourceMapsExamplesLogic'
import { SourceMapsExamplesModal } from './SourceMapsExamplesModal'
import { SourceMapsFixModal } from './SourceMapsFixModal'
import { SOURCE_MAPS_DOCS_URL, SOURCE_MAPS_PLATFORM_LABELS, sourceMapsFixWizardLogic } from './sourceMapsFixWizardLogic'
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
    const { openExamples } = useActions(sourceMapsExamplesLogic)
    const { dismissBanner } = useActions(errorTrackingBannersLogic)
    const platform = recommendation.meta.platform ?? 'javascript'
    const labels = SOURCE_MAPS_PLATFORM_LABELS[platform]
    const percent = Math.round((recommendation.meta.unresolved_pct ?? 0) * 100)

    useOnMountEffect(() => {
        posthog.capture('error_tracking_source_maps_banner_shown', {
            unresolved_pct: percent,
            lookback_hours: recommendation.meta.lookback_hours,
            platform,
        })
    })

    return (
        <>
            <BannerCallout
                illustration={WizardHog}
                title={`${percent}% of ${labels.platform} frames that need ${labels.symbols} are missing them`}
                description={
                    <>
                        Upload {labels.symbols} to see your original code.{' '}
                        <Link
                            className="whitespace-nowrap"
                            onClick={() => openExamples(platform)}
                            data-attr="error-tracking-source-maps-banner-examples"
                        >
                            See examples
                        </Link>
                    </>
                }
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
            <SourceMapsExamplesModal />
        </>
    )
}
