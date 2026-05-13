import { useActions, useValues } from 'kea'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { LaunchStep, SocialPost, founderLogic } from '../scenes/founderLogic'

export function Step3(): JSX.Element {
    const { productDescription, gtmState, gtmPolling } = useValues(founderLogic)
    const { setProductDescription, generateStrategy } = useActions(founderLogic)

    const isLoading = gtmPolling || gtmState?.status === 'pending' || gtmState?.status === 'running'
    const result = gtmState?.status === 'completed' ? gtmState.result : null
    const error = gtmState?.status === 'failed' ? gtmState.error : null

    return (
        <div className="space-y-4 max-w-2xl">
            <h2 className="text-xl font-semibold">Launch playbook</h2>
            <p className="text-muted">
                Describe your product and get a ready-to-execute launch plan with copy-paste content for Product Hunt,
                LinkedIn, Twitter, Reddit, and more.
            </p>

            <LemonTextArea
                placeholder="e.g. I built a coworking space app that helps freelancers find and book desks near them. It has a map view, instant booking, and a community chat feature..."
                value={productDescription}
                onChange={(value) => setProductDescription(value)}
                minRows={4}
                maxRows={8}
            />

            <LemonButton
                type="primary"
                onClick={generateStrategy}
                loading={isLoading}
                disabled={productDescription.trim().length < 10}
            >
                Generate launch plan
            </LemonButton>

            {isLoading && (
                <div className="flex items-center gap-2 text-muted">
                    <Spinner />
                    <span>Generating your launch playbook... this takes ~30-60 seconds</span>
                </div>
            )}

            {error && <div className="text-danger bg-danger-highlight rounded p-3">{error}</div>}

            {result && (
                <div className="space-y-6 mt-6">
                    <div className="border rounded p-4 space-y-3">
                        <h3 className="font-semibold text-lg">Launch strategy</h3>
                        <p>{result.launch_summary}</p>
                        <div className="flex flex-wrap gap-2 mt-2">
                            {result.target_communities.map((community: string, i: number) => (
                                <span
                                    key={i}
                                    className="text-xs bg-primary-highlight text-primary rounded-full px-2.5 py-1"
                                >
                                    {community}
                                </span>
                            ))}
                        </div>
                    </div>

                    <div className="space-y-4">
                        <h3 className="font-semibold text-lg">Step-by-step plan</h3>
                        {result.steps.map((step: LaunchStep, i: number) => (
                            <div key={i} className="border rounded p-4 space-y-3">
                                <div className="flex items-start gap-3">
                                    <span className="flex-shrink-0 w-7 h-7 rounded-full bg-primary text-white flex items-center justify-center text-sm font-bold">
                                        {i + 1}
                                    </span>
                                    <div className="flex-1">
                                        <div className="flex items-center justify-between">
                                            <h4 className="font-semibold">{step.title}</h4>
                                            <div className="flex gap-2">
                                                <span className="text-xs text-muted bg-bg-light px-2 py-0.5 rounded">
                                                    {step.timeline}
                                                </span>
                                                <span className="text-xs text-primary bg-primary-highlight px-2 py-0.5 rounded">
                                                    {step.channel}
                                                </span>
                                            </div>
                                        </div>
                                        <p className="text-sm text-muted mt-1">{step.description}</p>
                                    </div>
                                </div>

                                {step.ready_to_use_content.length > 0 && (
                                    <div className="ml-10 space-y-2">
                                        {step.ready_to_use_content.map((post: SocialPost, j: number) => (
                                            <div key={j} className="bg-bg-light rounded p-3 space-y-2">
                                                <div className="flex items-center justify-between">
                                                    <span className="text-xs font-semibold uppercase">
                                                        {post.platform}
                                                    </span>
                                                    <LemonButton
                                                        size="xsmall"
                                                        type="secondary"
                                                        onClick={() => void navigator.clipboard.writeText(post.content)}
                                                    >
                                                        Copy
                                                    </LemonButton>
                                                </div>
                                                <p className="text-sm whitespace-pre-wrap font-mono">{post.content}</p>
                                                <p className="text-xs text-muted italic">{post.tips}</p>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
