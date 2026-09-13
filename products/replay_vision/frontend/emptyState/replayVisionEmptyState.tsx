import * as noirDeskPng from '@posthog/brand/hoggies/png/noir-5'
import { IconEye } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { visionDocsUrl } from '../components/DocsLink'
import { replayVisionSetupLogic } from '../replayVisionSetupLogic'
import { ReplayVisionObservationPreview } from './ReplayVisionObservationPreview'

const HedgehogNoirDesk = pngHoggie(noirDeskPng)

export const replayVisionEmptyState: SceneProductEmptyState = {
    statusLogic: replayVisionSetupLogic,
    config: {
        productKey: ProductKey.REPLAY_VISION,
        productName: 'Replay Vision',
        icon: <IconEye />,
        // Replay vision shares session replay's product color (see the manifest's iconColor).
        accentColor: 'var(--color-product-session-replay-light)',
        accentColorDark: 'var(--color-product-session-replay-dark)',
        hedgehog: HedgehogNoirDesk,
        hedgehogPlacement: 'beside',
        text: {
            'needs-setup': {
                headline: "AI watches your recordings so you don't have to",
                lead: 'Describe what to look for in plain language. A scanner watches each new session recording for it. Every result is an event you can query, graph, and alert on.',
                hint: 'Fastest way in: the setup agent turns on session replay if needed, then reads your codebase and creates scanners for your key flows:',
            },
        },
        wizard: { slug: 'replay-vision', pinProjectId: true },
        primaryAction: {
            label: 'Create a scanner yourself',
            to: urls.replayVisionTemplates(),
        },
        docsUrl: visionDocsUrl(),
        previewLabel: 'Example scanner results',
        Preview: ReplayVisionObservationPreview,
    },
}
