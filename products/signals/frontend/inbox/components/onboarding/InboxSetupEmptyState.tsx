import * as selfDrivingPng from '@posthog/brand/hoggies/png/self-driving'

import { pngHoggie } from 'lib/brand/hoggies'
import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'
import type { ProductEmptyStateConfig } from 'lib/components/ProductEmptyState/types'
import { IconSelfDriving } from 'lib/lemon-ui/icons'

import { ProductKey } from '~/queries/schema/schema-general'

import { InboxReportPreview } from './InboxReportPreview'
import { InboxSetupActions } from './InboxSetupActions'

const HedgehogSelfDriving = pngHoggie(selfDrivingPng)

const INBOX_SETUP_EMPTY_STATE: ProductEmptyStateConfig = {
    productKey: ProductKey.SELF_DRIVING,
    productName: 'Self-Driving',
    icon: <IconSelfDriving />,
    accentColor: 'var(--color-product-self-driving-light)',
    accentColorDark: 'var(--color-product-self-driving-dark)',
    hedgehog: HedgehogSelfDriving,
    hedgehogPlacement: 'beside',
    text: {
        'needs-setup': {
            headline: 'Let PostHog find what needs your attention',
            lead: 'AI does the research for you. Get reports with evidence and next steps. Ship fixes with your agent of choice, or let PostHog do it for you.',
        },
    },
    PrimaryAction: InboxSetupActions,
    docsUrl: 'https://posthog.com/docs/self-driving',
    previewLabel: 'Example report',
    previewClassName: 'items-center [&>*]:w-full [&>*]:max-w-120',
    Preview: InboxReportPreview,
    // An inbox that isn't set up is an empty list, so skipping would reveal nothing.
    skippable: false,
}

/**
 * Rendered by the inbox's own takeover gate rather than the scene-level one: the setup flow it opens
 * lives inside the same scene.
 */
export function InboxSetupEmptyState(): JSX.Element {
    return <ProductEmptyState config={INBOX_SETUP_EMPTY_STATE} mode="needs-setup" />
}
