import { Badge, Button, Card } from '@posthog/quill'

import {
    ImageName,
    Source,
    Sources,
    Workflow,
    devStackBadge,
    devStackProgress,
    devStackState,
    fresh,
    imageNames,
    imageState,
    labels,
    selectedWorkflow,
    variants,
} from './infrastructureTypes'

function timestamp(value: string): string {
    return new Date(value).toISOString().replace('T', ' ').slice(0, 16) + ' UTC'
}

export function StageInspector({
    selected,
    sources,
    workflow,
    workflowLoading,
    onWorkflow,
}: {
    selected: string
    sources: Sources
    workflow: { id: string; source: Source<Workflow> } | null
    workflowLoading: boolean
    onWorkflow: (id: string) => void
}): JSX.Element {
    const source = sources[selected as keyof Sources]
    const image = sources.custom?.data?.images.find((item) => item.id === selected)
    const registry = imageNames.includes(selected as ImageName) ? sources[selected as ImageName]?.data : null
    const run = selectedWorkflow(selected, sources, workflow)
    const devState = devStackState(sources)
    const devBadge = devStackBadge(sources)
    const devStack = sources.dev_stack?.data
    const progress = devStackProgress(sources)
    return (
        <Card className="inspector">
            <div className="inspector-header">
                <span className="eyebrow">Stage evidence</span>
                {selected === 'dev_stack' ? (
                    <Badge variant={devBadge.variant}>{devBadge.label}</Badge>
                ) : (
                    <Badge variant={fresh(source) ? 'success' : 'default'}>
                        {fresh(source) ? 'Source fresh' : image ? 'Custom image' : 'Unverified'}
                    </Badge>
                )}
            </div>
            <h2>{image ? `Image ${image.id.slice(0, 8)}` : selected.replace('_', ' ')}</h2>
            {source?.observed_at && (
                <p className="muted">
                    Observed {new Date(source.observed_at).toISOString().replace('T', ' ').slice(0, 19)} UTC
                </p>
            )}
            {source?.status === 'error' && (
                <>
                    <p className="alert">{source.error || 'Source unavailable. Refresh to retry.'}</p>
                    {source.data !== null && <p className="muted">Values below are from the last successful read.</p>}
                </>
            )}
            {selected === 'package' && (
                <p>Latest published npm version. A newer package does not mean the sandbox version pin has merged.</p>
            )}
            {selected === 'release' && (
                <>
                    <p>
                        Master's sandbox version pin and the latest five workflow runs. Unrelated changes can skip image
                        builds. Build and promotion results below do not prove custom-image adoption.
                    </p>
                    {sources.release?.data?.runs_error && (
                        <p className="alert">{`Build history incomplete. ${sources.release.data.runs_error}`}</p>
                    )}
                    {sources.release?.data?.runs_stale && !!sources.release.data.runs.length && (
                        <p className="muted">
                            Build history is from the last successful read
                            {sources.release.data.runs_observed_at
                                ? ` at ${new Date(sources.release.data.runs_observed_at).toISOString().replace('T', ' ').slice(0, 19)} UTC`
                                : ''}
                            .
                        </p>
                    )}
                    {sources.release?.data?.runs.map((item) => (
                        <div className="platform-details" key={item.id}>
                            <a className="run-link" href={item.html_url} target="_blank" rel="noreferrer">
                                <code>{item.head_sha.slice(0, 8)}</code>
                                <span>{`Workflow ${item.conclusion || item.status} ↗`}</span>
                            </a>
                            {item.build_jobs_error ? (
                                <p className="alert">{`Build jobs unavailable. ${item.build_jobs_error}`}</p>
                            ) : (
                                !item.build_jobs?.length && <p>Build jobs not observed.</p>
                            )}
                            {item.build_jobs?.map((job) => (
                                <div key={job.name}>
                                    <p>{`${job.name}: ${job.conclusion || job.status}`}</p>
                                    {job.promotion && <p>{`Base promotion: ${job.promotion}`}</p>}
                                </div>
                            ))}
                        </div>
                    ))}
                </>
            )}
            {registry && (
                <>
                    <div>
                        <h3>Version pin and base lineage</h3>
                        <Badge variant={variants[imageState(sources, selected as ImageName)]}>
                            {labels[imageState(sources, selected as ImageName)]}
                        </Badge>
                    </div>
                    <p className="digest">
                        <code>{registry.reference}</code>
                    </p>
                    {registry.platforms.map((platform) => (
                        <div className="platform-details" key={platform.arch}>
                            <h3>{platform.arch}</h3>
                            <dl>
                                <dt>Agent</dt>
                                <dd>{platform.version || 'Unrecorded'}</dd>
                                <dt>Revision</dt>
                                <dd>
                                    <code>{platform.revision || 'Unrecorded'}</code>
                                </dd>
                                <dt>Base revision</dt>
                                <dd>
                                    <code>{platform.base_revision || 'Unrecorded'}</code>
                                </dd>
                                <dt>Inputs digest</dt>
                                <dd>
                                    <code>{platform.inputs_digest || 'Unrecorded'}</code>
                                </dd>
                            </dl>
                        </div>
                    ))}
                </>
            )}
            {selected === 'custom' && (
                <>
                    <p>
                        Each image below shows its last successful base, pending refresh target and latest build state.
                    </p>
                    <p>
                        A failed refresh can leave the image ready on its previous base. Images without a published
                        version or a build spec are not eligible for automatic refresh.
                    </p>
                    <p>Choose Inspect on an image to read the latest Temporal execution.</p>
                </>
            )}
            {selected === 'dev_stack' && (
                <>
                    {progress && <Badge variant={progress.variant}>{progress.label}</Badge>}
                    {devStack?.protected && (
                        <>
                            <dl>
                                <dt>Active → target</dt>
                                <dd>{`${devStack.active_generation || 'None'} → ${devStack.generation || 'None'}`}</dd>
                                <dt>Active agent</dt>
                                <dd>{devStack.active_agent_version || 'Unrecorded'}</dd>

                                <dt>Last activation</dt>
                                <dd>{devStack.activated_at ? timestamp(devStack.activated_at) : 'Not activated'}</dd>
                                <dt>Requested</dt>
                                <dd>{devStack.requested_at ? timestamp(devStack.requested_at) : 'Not requested'}</dd>
                                <dt>Target observed</dt>
                                <dd>
                                    {devStack.target_observed_at
                                        ? timestamp(devStack.target_observed_at)
                                        : 'Not observed'}
                                </dd>
                                <dt>Attempt started</dt>
                                <dd>
                                    {devStack.attempt_started_at
                                        ? timestamp(devStack.attempt_started_at)
                                        : 'Not started'}
                                </dd>
                                <dt>Next retry</dt>
                                <dd>{devStack.next_retry_at ? timestamp(devStack.next_retry_at) : 'None scheduled'}</dd>
                            </dl>
                            {devStack.reason && <p className="alert">{devStack.reason}</p>}
                            {devStack.observation_error && <p className="alert">{devStack.observation_error}</p>}
                            {devStack.auto_refresh === false && (
                                <p className="alert">Automatic base updates are paused after a rollback.</p>
                            )}
                            <h3>Active image</h3>
                            <code className="digest">
                                {devStack.active_image_id || 'No verified image. Tasks use the VM base.'}
                            </code>
                            {devStack.desired_base_reference &&
                                devStack.desired_base_reference !== sources.vm?.data?.reference && (
                                    <>
                                        <h3>Desired VM base</h3>
                                        <code className="digest">{devStack.desired_base_reference}</code>
                                    </>
                                )}
                            <p className="muted">
                                Base adoption and bake progress are independent. A nightly rebuild can run while the
                                base is current.
                            </p>
                        </>
                    )}
                    <p>
                        {devState === 'waiting'
                            ? 'The last successful bake uses a different VM base. A fresh source read does not mean the bake has caught up.'
                            : devState === 'current'
                              ? 'The last successful bake matches the current VM base.'
                              : 'Fresh bake and VM base records are needed to verify adoption. Missing records do not prove a failed bake.'}
                    </p>
                    <h3>Last successful bake base</h3>
                    <p className="digest">
                        <code>{sources.dev_stack?.data?.base_image_reference || 'No recorded base'}</code>
                    </p>
                    <h3>Current VM base</h3>
                    <p className="digest">
                        <code>{sources.vm?.data?.reference || 'No recorded base'}</code>
                    </p>
                    {!fresh(sources.vm) && <p className="muted">The VM base source is unavailable or stale.</p>}
                    <p>
                        Base changes are checked every 2 minutes; the scheduled bake runs daily at 06:45 UTC when
                        enabled.
                    </p>
                </>
            )}
            {image && (
                <>
                    <dl>
                        <dt>Project</dt>
                        <dd>{image.team_id}</dd>
                        <dt>Image status</dt>
                        <dd>{image.status}</dd>
                        <dt>Published version</dt>
                        <dd>{image.version}</dd>
                        <dt>Last error</dt>
                        <dd>{image.has_error ? 'Recorded' : 'None recorded'}</dd>
                    </dl>
                    <h3>Successful base</h3>
                    <code className="digest">{image.base_image_reference || 'Unrecorded'}</code>
                    <h3>Pending target</h3>
                    <code className="digest">{image.base_image_refresh_reference || 'None recorded'}</code>
                </>
            )}
            {(image || (selected === 'dev_stack' && (!devStack?.protected || devStack.workflow_url))) && (
                <>
                    {workflow?.id === selected && workflow.source.status === 'error' && (
                        <p className="alert" role="alert">
                            Could not read the build from Temporal. Select Read latest build to retry.
                        </p>
                    )}
                    <Button
                        variant="outline"
                        loading={workflowLoading}
                        onClick={() => onWorkflow(selected)}
                        data-attr="infra-read-workflow"
                    >
                        Read latest build
                    </Button>
                    {run && (
                        <>
                            <h3>Latest Temporal execution</h3>
                            <p>
                                {!fresh(run)
                                    ? 'Temporal evidence is unavailable or stale. Read the latest build to update it.'
                                    : run.data?.status === 'not_found'
                                      ? 'No retained execution found.'
                                      : run.data?.status}
                            </p>
                            {run.observed_at && <p>Observed {new Date(run.observed_at).toISOString()}</p>}
                            {run.data?.started_at && <p>Started {new Date(run.data.started_at).toISOString()}</p>}
                            {run.data?.activities.map((activity) => (
                                <p key={activity.name}>
                                    <code>{activity.name}</code>
                                    <span>{` · ${activity.state} · attempt ${activity.attempt}`}</span>
                                </p>
                            ))}
                        </>
                    )}
                    <a
                        href={run?.data?.url || image?.workflow_url || sources.dev_stack?.data?.workflow_url}
                        target="_blank"
                        rel="noreferrer"
                    >
                        Open Temporal history ↗
                    </a>
                    <p>
                        {selected === 'dev_stack' && devStack?.protected
                            ? 'This execution belongs to the displayed attempt.'
                            : 'Workflow IDs are reused. This is the latest execution, which may target an earlier base.'}
                    </p>
                </>
            )}
        </Card>
    )
}
