import { VisionDocsLink } from '../../components/DocsLink'
import { CreateScannerButton } from './CreateScannerButton'
import { ExampleObservations } from './ExampleObservations'

/**
 * What the What to watch tab shows a reader who has no scanners: what the feed is for, an example of
 * the card it fills with, and the way to start one.
 */
export function WatchFeedIntro(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col items-center gap-2 text-center">
                <h3 className="text-xl font-semibold m-0">See your most notable observations here</h3>
                <p className="text-secondary m-0 max-w-lg">
                    Scanners watch each new session recording and cite the moment they found. We surface the most
                    notable ones here.
                </p>
                <div className="flex flex-wrap items-center justify-center gap-2 mt-1">
                    <CreateScannerButton
                        acceptedLabel="Create your first scanner"
                        dataAttr="vision-watch-feed-create-scanner"
                        size="medium"
                    />
                    <VisionDocsLink page="creating-scanners" dataAttr="vision-watch-feed-docs-link">
                        Learn how scanners work
                    </VisionDocsLink>
                </div>
            </div>

            <ExampleObservations />
        </div>
    )
}
