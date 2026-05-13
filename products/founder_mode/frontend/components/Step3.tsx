import { useActions, useValues } from 'kea'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { GTMStep, step3Logic } from './step3Logic'

export function Step3(): JSX.Element {
    const { productDescription, loading, result, error } = useValues(step3Logic)
    const { setProductDescription, generateStrategy } = useActions(step3Logic)

    return (
        <div className="space-y-4 max-w-2xl">
            <h2 className="text-xl font-semibold">Go-to-market strategy</h2>
            <p className="text-muted">Describe your product idea and we'll generate an actionable go-to-market plan.</p>

            <LemonTextArea
                placeholder="e.g. I want to build a coworking space app that helps freelancers find and book desks near them..."
                value={productDescription}
                onChange={(value) => setProductDescription(value)}
                minRows={4}
                maxRows={8}
            />

            <LemonButton
                type="primary"
                onClick={generateStrategy}
                loading={loading}
                disabled={productDescription.trim().length < 10}
            >
                Generate strategy
            </LemonButton>

            {error && <div className="text-danger bg-danger-highlight rounded p-3">{error}</div>}

            {result && (
                <div className="space-y-6 mt-6">
                    <div className="border rounded p-4 space-y-3">
                        <h3 className="font-semibold text-lg">Strategy overview</h3>
                        <p>{result.strategy_description}</p>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                            <div className="bg-bg-light rounded p-3">
                                <span className="text-xs font-semibold uppercase text-muted">Target audience</span>
                                <p className="mt-1 text-sm">{result.target_audience}</p>
                            </div>
                            <div className="bg-bg-light rounded p-3">
                                <span className="text-xs font-semibold uppercase text-muted">Value proposition</span>
                                <p className="mt-1 text-sm">{result.value_proposition}</p>
                            </div>
                        </div>
                    </div>

                    <div className="space-y-3">
                        <h3 className="font-semibold text-lg">Action plan</h3>
                        {result.steps.map((step: GTMStep, i: number) => (
                            <div key={i} className="border rounded p-4">
                                <div className="flex items-start gap-3">
                                    <span className="flex-shrink-0 w-7 h-7 rounded-full bg-primary text-white flex items-center justify-center text-sm font-bold">
                                        {i + 1}
                                    </span>
                                    <div className="flex-1 space-y-2">
                                        <div className="flex items-center justify-between">
                                            <h4 className="font-semibold">{step.title}</h4>
                                            <span className="text-xs text-muted bg-bg-light px-2 py-0.5 rounded">
                                                {step.timeline}
                                            </span>
                                        </div>
                                        <p className="text-sm text-muted">{step.description}</p>
                                        <ul className="list-disc list-inside text-sm space-y-1">
                                            {step.key_actions.map((action: string, j: number) => (
                                                <li key={j}>{action}</li>
                                            ))}
                                        </ul>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}
