import * as directorPng from '@posthog/brand/hoggies/png/director'
import { IconRewindPlay } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { SessionReplayPreview } from './SessionReplayPreview'
import { sessionReplaySetupLogic } from './sessionReplaySetupLogic'

const HedgehogDirector = pngHoggie(directorPng)

export const sessionReplayEmptyState: SceneProductEmptyState = {
    statusLogic: sessionReplaySetupLogic,
    config: {
        productKey: ProductKey.SESSION_REPLAY,
        productName: 'Session replay',
        icon: <IconRewindPlay />,
        accentColor: 'var(--color-product-session-replay-light)',
        accentColorDark: 'var(--color-product-session-replay-dark)',
        hedgehog: HedgehogDirector,
        text: {
            'needs-setup': {
                headline: 'Watch how people really use your product',
                lead: 'Record sessions and replay every click, scroll, and console log. See where users get stuck, reproduce bugs exactly as they happened, and jump from any event or error to the moment it occurred.',
                hint: 'Already sending events with posthog-js? One click and recording starts:',
            },
            'waiting-for-data': {
                headline: 'Recording is on. Waiting for the first session',
                lead: 'New sessions start recording as users visit your site. The first replays usually show up here a few minutes after a visit.',
            },
        },
        primaryAction: {
            label: 'Enable session recording',
            onClick: () => {
                teamLogic.findMounted()?.actions.updateCurrentTeam({ session_recording_opt_in: true })
            },
            accessControl: {
                resourceType: AccessControlResourceType.SessionRecording,
                minAccessLevel: AccessControlLevel.Editor,
            },
        },
        docsUrl: 'https://posthog.com/docs/session-replay',
        previewLabel: 'Your recordings, once sessions arrive',
        Preview: SessionReplayPreview,
    },
}
