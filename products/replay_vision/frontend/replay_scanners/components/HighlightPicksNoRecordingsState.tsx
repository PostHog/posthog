import { useActions, useMountedLogic } from 'kea'

import * as directorPng from '@posthog/brand/hoggies/png/director'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { highlightPicksLogic } from '../highlightPicksLogic'
import { HighlightPicksStateFrame } from './HighlightPicksStateFrame'

const HedgehogDirector = pngHoggie(directorPng)

export function HighlightPicksNoRecordingsState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { emptyStateAction } = useActions(useMountedLogic(highlightPicksLogic))
    return (
        <HighlightPicksStateFrame
            size={size}
            image={HedgehogDirector}
            title="No recordings to scan yet"
            body="Scanners watch recordings, so there is nothing for them to see until sessions arrive. Highlights show up once recording starts."
            dataAttr="vision-highlight-picks-no-recordings"
            footer={
                <Link
                    to="https://posthog.com/docs/session-replay"
                    target="_blank"
                    className="mt-1"
                    onClick={() => emptyStateAction('no-recordings', 'replay_docs')}
                    data-attr="vision-highlight-picks-no-recordings-docs"
                >
                    Session replay docs
                </Link>
            }
        >
            <LemonButton
                type="primary"
                size={size === 'large' ? 'medium' : 'small'}
                fullWidth
                center
                to={urls.onboarding({ productKey: ProductKey.SESSION_REPLAY, stepKey: OnboardingStepKey.INSTALL })}
                onClick={() => emptyStateAction('no-recordings', 'setup_replay')}
                data-attr="vision-highlight-picks-no-recordings-setup"
            >
                Set up session replay
            </LemonButton>
        </HighlightPicksStateFrame>
    )
}
