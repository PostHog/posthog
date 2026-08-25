import * as megaphonePng from '@posthog/brand/hoggies/png/megaphone'
import { IconExternal } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { LinkPreview } from './LinkPreview'
import { linksSetupLogic } from './linksSetupLogic'

const HedgehogMegaphone = pngHoggie(megaphonePng)

export const linksEmptyState: SceneProductEmptyState = {
    statusLogic: linksSetupLogic,
    // The whole product is behind this flag (nav-gated); flag-off users never reach the scene.
    featureFlag: FEATURE_FLAGS.LINKS,
    config: {
        productKey: ProductKey.LINKS,
        productName: 'Links',
        icon: <IconExternal />,
        accentColor: 'var(--color-product-links-light)',
        accentColorDark: 'var(--color-product-links-dark)',
        hedgehog: HedgehogMegaphone,
        text: {
            'needs-setup': {
                headline: 'Short links you control after sharing them',
                lead: 'Turn long URLs into short links for emails, social posts, referral programs, and QR codes. Each link redirects to whatever destination you choose, and you can change that destination at any time without re-sharing the link.',
            },
        },
        primaryAction: { label: 'Create your first link', to: urls.link('new') },
        skippable: false,
        previewLabel: 'Your links, once created',
        Preview: LinkPreview,
    },
}
