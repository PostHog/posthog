import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { sourceMapsExamplesLogic } from './sourceMapsExamplesLogic'
import { SourceMapsExamplesTable } from './SourceMapsExamplesTable'
import { SOURCE_MAPS_DOCS_URL, SOURCE_MAPS_PLATFORM_LABELS } from './sourceMapsFixWizardLogic'

export function SourceMapsExamplesModal(): JSX.Element {
    const { isOpen, platform, examples, examplesLoading, examplesFailed } = useValues(sourceMapsExamplesLogic)
    const { closeExamples, loadExamples } = useActions(sourceMapsExamplesLogic)
    const labels = SOURCE_MAPS_PLATFORM_LABELS[platform ?? 'javascript']
    const lookbackHours = examples?.lookback_hours ?? 24

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeExamples}
            width={880}
            title={`${labels.platform} frames missing ${labels.symbols}`}
            description={`The files and builds with the most frames missing ${labels.symbols} in the last ${lookbackHours} hours.`}
            footer={
                <>
                    <LemonButton type="secondary" to={SOURCE_MAPS_DOCS_URL} targetBlank>
                        Read docs
                    </LemonButton>
                    <LemonButton type="primary" onClick={closeExamples}>
                        Close
                    </LemonButton>
                </>
            }
        >
            {examplesLoading || (examples === null && !examplesFailed) ? (
                <div className="flex justify-center py-8">
                    <Spinner />
                </div>
            ) : examplesFailed ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => platform && loadExamples(platform) }}
                >
                    Couldn't load the examples. Try again, and if it keeps failing, contact support.
                </LemonBanner>
            ) : !examples?.results.length ? (
                <p className="text-secondary text-center py-8 mb-0">
                    No frames are missing {labels.symbols} in the last {lookbackHours} hours.
                </p>
            ) : (
                <SourceMapsExamplesTable examples={examples.results} />
            )}
        </LemonModal>
    )
}
