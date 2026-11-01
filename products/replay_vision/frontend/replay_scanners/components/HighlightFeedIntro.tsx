import { VisionDocsLink } from '../../components/DocsLink'
import { CreateScannerButton } from './CreateScannerButton'
import { ExampleObservations } from './ExampleObservations'

/**
 * What the Highlights tab shows a reader who has no scanners: what the feed is for, an example of
 * the card it fills with, and the way to start one.
 */
export function HighlightFeedIntro(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col items-center gap-2 text-center">
                <h3 className="text-xl font-semibold m-0">Sessions worth watching show up here</h3>
                <p className="text-secondary m-0 max-w-lg">
                    Create a scanner to analyze new session recordings. Sessions that stand out in its results show up
                    here.
                </p>
                <div className="flex flex-wrap items-center justify-center gap-2 mt-1">
                    <CreateScannerButton
                        acceptedLabel="Create your first scanner"
                        dataAttr="vision-highlight-feed-create-scanner"
                        size="medium"
                    />
                    <VisionDocsLink page="creating-scanners" dataAttr="vision-highlight-feed-docs-link">
                        Learn how scanners work
                    </VisionDocsLink>
                </div>
            </div>

            <ExampleObservations />
        </div>
    )
}
