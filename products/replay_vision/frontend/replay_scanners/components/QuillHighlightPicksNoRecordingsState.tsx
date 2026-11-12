import { useActions, useMountedLogic } from 'kea'

import * as directorPng from '@posthog/brand/hoggies/png/director'
import { Button } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { highlightPicksLogic } from '../highlightPicksLogic'
import { QuillHighlightPicksStateFrame } from './QuillHighlightPicksStateFrame'

const HedgehogDirector = pngHoggie(directorPng)

export function QuillHighlightPicksNoRecordingsState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const { emptyStateAction } = useActions(useMountedLogic(highlightPicksLogic))
    return (
        <QuillHighlightPicksStateFrame
            size={size}
            image={HedgehogDirector}
            title="No recordings to scan yet"
            body="Scanners watch recordings, so there is nothing for them to see until sessions arrive. Highlights show up once recording starts."
            dataAttr="vision-highlight-picks-no-recordings"
            footer={
                <Button
                    variant="link"
                    size="inline"
                    className="mt-1"
                    render={<LinkPrimitive to="https://posthog.com/docs/session-replay" target="_blank" />}
                    onClick={() => emptyStateAction('no-recordings', 'replay_docs')}
                    data-attr="vision-highlight-picks-no-recordings-docs"
                >
                    Session replay docs
                </Button>
            }
        >
            <Button
                variant="primary"
                size={size === 'large' ? 'default' : 'sm'}
                className="w-full"
                render={
                    <LinkPrimitive
                        to={urls.onboarding({
                            productKey: ProductKey.SESSION_REPLAY,
                            stepKey: OnboardingStepKey.INSTALL,
                        })}
                    />
                }
                onClick={() => emptyStateAction('no-recordings', 'setup_replay')}
                data-attr="vision-highlight-picks-no-recordings-setup"
            >
                Set up session replay
            </Button>
        </QuillHighlightPicksStateFrame>
    )
}
