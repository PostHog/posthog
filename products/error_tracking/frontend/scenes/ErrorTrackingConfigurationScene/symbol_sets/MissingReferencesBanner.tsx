import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { symbolSetLogic } from './symbolSetLogic'

type PlatformCopy = {
    name: string
    reference: string
    docsUrl: string
}

const PLATFORM_COPY: Record<string, PlatformCopy> = {
    hermes: {
        name: 'React Native',
        reference: 'chunk ID',
        docsUrl: 'https://posthog.com/docs/error-tracking/upload-source-maps/react-native',
    },
    proguard: {
        name: 'Android',
        reference: 'mapping ID',
        docsUrl: 'https://posthog.com/docs/error-tracking/upload-mappings/android',
    },
}

export function MissingReferencesBanner(): JSX.Element | null {
    const { missingReferences } = useValues(symbolSetLogic)

    if (!missingReferences) {
        return null
    }
    const { lookback_hours } = missingReferences

    return (
        <>
            {missingReferences.platforms.map(({ platform, frame_count }) => {
                const copy = PLATFORM_COPY[platform]
                if (!copy) {
                    return null
                }
                return (
                    <LemonBanner
                        key={platform}
                        type="warning"
                        action={{ children: `${copy.name} docs`, to: copy.docsUrl, targetBlank: true }}
                    >
                        <div className="font-semibold">
                            Some {copy.name} frames arrive without a {copy.reference}
                        </div>
                        <div className="text-sm">
                            {pluralize(frame_count, 'frame', 'frames')} reached PostHog in the last{' '}
                            {pluralize(lookback_hours, 'hour', 'hours')} with no {copy.reference}. Symbol sets only
                            match frames that carry one, so these stack traces stay minified no matter how many you
                            upload. Check that your build injects {copy.reference}s before it uploads them.
                        </div>
                    </LemonBanner>
                )
            })}
        </>
    )
}
