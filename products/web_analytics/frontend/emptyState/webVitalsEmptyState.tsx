import * as drivingHogzillaPng from '@posthog/brand/hoggies/png/driving-hogzilla'
import { IconPieChart } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { WebVitalsPreview } from './WebVitalsPreview'
import { webVitalsSetupLogic } from './webVitalsSetupLogic'

const HedgehogDriving = pngHoggie(drivingHogzillaPng)

export const webVitalsEmptyState: SceneProductEmptyState = {
    statusLogic: webVitalsSetupLogic,
    // Only the web vitals tab has a setup state; the analytics tabs the same
    // scene module serves are never gated.
    scenes: [Scene.WebAnalyticsWebVitals],
    config: {
        productKey: ProductKey.WEB_ANALYTICS,
        productName: 'Web vitals',
        icon: <IconPieChart />,
        accentColor: 'var(--color-product-web-analytics-light)',
        accentColorDark: 'var(--color-product-web-analytics-dark)',
        hedgehog: HedgehogDriving,
        text: {
            'needs-setup': {
                headline: 'Know how fast your site feels',
                lead: 'Capture Core Web Vitals (LCP, CLS, INP, and FCP) from real visits and see which pages drag them down. Captured events count toward your event quota, and you can turn this off any time in settings.',
                hint: 'Already sending pageviews with posthog-js? One click and vitals start flowing:',
            },
            'waiting-for-data': {
                headline: 'Autocapture is on. Waiting for the first vitals',
                lead: 'Web vitals arrive with your next page visits. Open your site in another tab and the first samples show up here on their own.',
            },
        },
        primaryAction: {
            label: 'Enable web vitals autocapture',
            onClick: () => {
                teamLogic.findMounted()?.actions.updateCurrentTeam({ autocapture_web_vitals_opt_in: true })
            },
            accessControl: {
                resourceType: AccessControlResourceType.WebAnalytics,
                minAccessLevel: AccessControlLevel.Editor,
            },
            // pinned: Playwright and autocapture dashboards select the old enable button by this attr
            dataAttr: 'web-vitals-enable',
        },
        docsUrl: 'https://posthog.com/docs/web-analytics/web-vitals',
        previewLabel: 'Your vitals, once samples arrive',
        Preview: WebVitalsPreview,
    },
}
