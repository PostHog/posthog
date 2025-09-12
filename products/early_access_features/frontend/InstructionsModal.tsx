import { useValues } from 'kea'

import { LemonCollapse, LemonModal, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { FeatureFlagType } from '~/types'

import EarlyAccessFeatureImage from 'public/early-access-feature-demo.png'

interface InstructionsModalProps {
    flag: FeatureFlagType['key']
    visible: boolean
    onClose: () => void
}

export function InstructionsModal({ onClose, visible, flag }: InstructionsModalProps): JSX.Element {
    const { preflight } = useValues(preflightLogic)

    const getCloudPanels = (): JSX.Element => (
        <LemonCollapse
            className="mt-2 bg-surface-primary"
            defaultActiveKey="1"
            panels={[
                {
                    key: '1',
                    header: 'Option 1: Widget Site App',
                    content: (
                        <div>
                            Give your users a{' '}
                            <Link to={urls.hogFunctionNew('template-early-access-features')}>prebuilt widget</Link> to
                            opt-in to features
                            <img className="max-h-full max-w-full mt-2.5" src={EarlyAccessFeatureImage} />
                        </div>
                    ),
                },
                {
                    key: '2',
                    header: 'Option 2: Custom implementation',
                    content: (
                        <div>
                            <b>Opt user in</b>
                            <div>
                                <FeatureEnrollInstructions flag={flag} />
                            </div>

                            <b>Opt user out</b>
                            <div>
                                <FeatureUnenrollInstructions flag={flag} />
                            </div>

                            <b>Retrieve Previews</b>
                            <div>
                                <RetrievePreviewsInstructions />
                            </div>
                        </div>
                    ),
                },
            ]}
        />
    )

    const getSelfHostedPanels = (): JSX.Element => (
        <div>
            <b>Opt user in</b>
            <div>
                <FeatureEnrollInstructions flag={flag} />
            </div>

            <b>Opt user out</b>
            <div>
                <FeatureUnenrollInstructions flag={flag} />
            </div>

            <b>Retrieve Previews</b>
            <div>
                <RetrievePreviewsInstructions />
            </div>
        </div>
    )

    const panels: JSX.Element = preflight?.cloud ? getCloudPanels() : getSelfHostedPanels()

    return (
        <LemonModal title="How to implement opt-in feature flags" isOpen={visible} onClose={onClose} width={640}>
            <div>
                <div className="mb-2">
                    Implement manual release condition toggles to give your users the ability choose which features they
                    want to try
                </div>
                {panels}
            </div>
        </LemonModal>
    )
}

function FeatureEnrollInstructions({ flag }: { flag: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.updateEarlyAccessFeatureEnrollment("${flag}", true)
`}
        </CodeSnippet>
    )
}

function FeatureUnenrollInstructions({ flag }: { flag: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.updateEarlyAccessFeatureEnrollment("${flag}", false)
`}
        </CodeSnippet>
    )
}

function RetrievePreviewsInstructions(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`posthog.getEarlyAccessFeatures((previewItemData) => {
    // do something with early access feature
})
`}
        </CodeSnippet>
    )
}
