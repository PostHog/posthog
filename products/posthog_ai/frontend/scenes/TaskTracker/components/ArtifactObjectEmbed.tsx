import { useState } from 'react'

import { Spinner, cn } from '@posthog/quill-primitives'

import { EMBEDDED_PAGE_FRAME_NAME } from 'lib/utils/embeddedPageFrame'

/**
 * A cited object's own page, the same page its URL opens. The frame keeps that page's URL and navigation
 * apart from the task page, and the frame name makes the app show the page without its navigation.
 */
export function ArtifactObjectEmbed({ url, title }: { url: string; title: string }): JSX.Element {
    const [loaded, setLoaded] = useState(false)
    return (
        <div className="relative size-full">
            {!loaded && (
                <div className="absolute inset-0 flex items-center justify-center">
                    <Spinner />
                </div>
            )}
            {/* The page is the app's own, so it keeps its origin, scripts, forms and new tabs. The sandbox
                still stops it navigating the task page away. */}
            <iframe
                name={EMBEDDED_PAGE_FRAME_NAME}
                src={url}
                title={title}
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads allow-modals"
                className={cn('size-full border-0', !loaded && 'invisible')}
                onLoad={() => setLoaded(true)}
            />
        </div>
    )
}
