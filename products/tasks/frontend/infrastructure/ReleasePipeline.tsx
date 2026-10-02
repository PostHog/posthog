import { Card } from '@posthog/quill'

import { Sources, customState, fresh, imageNames, imageState, pinState, releaseBadge } from './infrastructureTypes'
import { PipelineNode } from './PipelineNode'

export function ReleasePipeline({
    sources,
    selected,
    onSelect,
}: {
    sources: Sources
    selected: string
    onSelect: (id: string) => void
}): JSX.Element {
    const base = fresh(sources.vm) ? sources.vm?.data?.reference : undefined
    const custom = sources.custom?.data
    const eligible = custom?.images.filter((image) => image.has_published_image && image.has_spec) || []
    const customCurrent = eligible.filter((image) => customState(image, base) === 'current').length
    const customFresh = fresh(sources.custom) && !!base && !custom?.truncated
    const devStack = sources.dev_stack?.data
    return (
        <Card className="pipeline-panel">
            <div className="section-title">
                <div>
                    <h2>Package → image → task</h2>
                    <p className="muted">
                        Current master tags, then regional image refreshes. Select a stage for evidence.
                    </p>
                </div>
            </div>
            <div className="pipeline-wrap">
                <div className="pipeline-stage-labels">
                    <span>01 Release and pin</span>
                    <span>02 Base image</span>
                    <span>03 Derived images</span>
                    <span>04 Regional fan-out</span>
                </div>
                <div className="pipeline">
                    <svg className="connections" viewBox="0 0 1040 540" preserveAspectRatio="none" aria-hidden="true">
                        <defs>
                            <marker
                                id="infra-arrow"
                                viewBox="0 0 8 8"
                                refX="7"
                                refY="4"
                                markerWidth="5"
                                markerHeight="5"
                                orient="auto-start-reverse"
                            >
                                <path d="M1 1 L7 4 L1 7" fill="none" stroke="currentColor" />
                            </marker>
                        </defs>
                        <path d="M126 145 V212 M236 262 H278 M498 262 H518 V147 H540 M498 262 H540 M498 262 H518 V377 H540 M760 377 H780 V322 H802 M760 377 H780 V442 H802" />
                        <path className="sibling-path" d="M126 312 V437 M126 339 H260 V487 H278" />
                        <text x="130" y="180">
                            version bump merged
                        </text>
                        <text x="783" y="256">
                            VM digest changes
                        </text>
                    </svg>
                    <PipelineNode
                        id="package"
                        title="Agent package"
                        subtitle={sources.package?.data?.version || 'Reading npm'}
                        state={fresh(sources.package) ? 'current' : 'unknown'}
                        badge={releaseBadge(sources, 'package')}
                        selected={selected}
                        onSelect={onSelect}
                    />
                    <PipelineNode
                        id="release"
                        title="Sandbox version pin"
                        subtitle={
                            sources.release?.data?.pin ||
                            (sources.release?.status === 'error' ? 'Release source unavailable' : 'Reading master')
                        }
                        state={pinState(sources)}
                        badge={releaseBadge(sources, 'release')}
                        selected={selected}
                        onSelect={onSelect}
                    />
                    {imageNames.map((name) => (
                        <PipelineNode
                            key={name}
                            id={name}
                            title={
                                {
                                    base: 'Sandbox base',
                                    notebook: 'Notebook',
                                    streamlit: 'Streamlit',
                                    pi: 'Pi',
                                    autoresearch: 'Autoresearch',
                                    vm: 'VM base',
                                }[name]
                            }
                            subtitle={
                                [...new Set(sources[name]?.data?.platforms.map((p) => p.version || '?'))].join(' / ') ||
                                'Reading registry'
                            }
                            state={imageState(sources, name)}
                            badge={releaseBadge(sources, name)}
                            selected={selected}
                            onSelect={onSelect}
                        />
                    ))}
                    <PipelineNode
                        id="custom"
                        title="Custom images"
                        subtitle={
                            custom
                                ? customFresh
                                    ? `${customCurrent} / ${eligible.length} eligible current`
                                    : `${eligible.length} eligible at last read`
                                : 'Reading inventory'
                        }
                        state={
                            !customFresh || eligible.length === 0
                                ? 'unknown'
                                : eligible.some((image) => customState(image, base) === 'failed')
                                  ? 'failed'
                                  : customCurrent === eligible.length
                                    ? 'current'
                                    : 'waiting'
                        }
                        selected={selected}
                        onSelect={onSelect}
                        badge={custom && !customFresh ? { label: 'Last seen', variant: 'default' } : undefined}
                    />
                    <PipelineNode
                        id="dev_stack"
                        title="PostHog dev stack"
                        subtitle={devStack?.name || 'Reading bake record'}
                        state={
                            !fresh(sources.dev_stack) || !base || !devStack?.base_image_reference
                                ? 'unknown'
                                : devStack.base_image_reference === base
                                  ? 'current'
                                  : 'waiting'
                        }
                        selected={selected}
                        onSelect={onSelect}
                        badge={
                            devStack && !fresh(sources.dev_stack)
                                ? { label: 'Last seen', variant: 'default' }
                                : undefined
                        }
                    />
                    <span className="parallel-caption">Notebook and Streamlit build alongside the base.</span>
                </div>
                <div className="pipeline-legend">
                    Release badges compare observed versions with npm latest. Last seen means cached evidence. Select an
                    image to check its pin and lineage. Running sandboxes are outside this view.
                </div>
            </div>
        </Card>
    )
}
