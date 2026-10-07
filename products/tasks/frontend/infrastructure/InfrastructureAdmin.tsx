import { useActions, useValues } from 'kea'

import { Badge, Button, Card } from '@posthog/quill'

import { CustomImageInventory } from './CustomImageInventory'
import { infrastructureLogic } from './infrastructureLogic'
import { fresh, imageNames, imageState, sourceNames } from './infrastructureTypes'
import { ReleasePipeline } from './ReleasePipeline'
import { SourceFreshness } from './SourceFreshness'
import { StageInspector } from './StageInspector'

export function InfrastructureAdmin({ region }: { region: string }): JSX.Element {
    const { sources, sourcesLoading, paused, workflow, workflowLoading, now, selected, showSources } =
        useValues(infrastructureLogic)
    const { loadSources, setPaused, loadWorkflow, setSelected, setShowSources } = useActions(infrastructureLogic)
    const data = sources || {}
    const connected = sourceNames.filter((name) => fresh(data[name], now)).length
    const current = imageNames.filter((name) => imageState(data, name) === 'current').length
    return (
        <div className="app-shell">
            <header className="app-header">
                <a className="brand" href="/admin/">
                    <span>PostHog</span>
                    <span className="muted">/ agent infrastructure</span>
                </a>
                <div className="header-right">
                    <Badge>{region}</Badge>
                    <span className="muted">Read-only</span>
                    <a href="/admin/">Django admin ↗</a>
                </div>
            </header>
            <div className="page-heading">
                <div>
                    <span className="eyebrow">Agent infrastructure</span>
                    <h1>Agent release pipeline</h1>
                    <p>Follow the published package into sandbox images and regional custom builds.</p>
                </div>
                <div className="refresh-controls">
                    <span className="muted">{paused ? 'Refresh paused' : 'Refreshes every minute'}</span>
                    <Button variant="outline" onClick={() => setPaused(!paused)} data-attr="infra-pause">
                        {paused ? 'Resume' : 'Pause'}
                    </Button>
                    <Button
                        variant="outline"
                        loading={sourcesLoading}
                        onClick={() => loadSources()}
                        data-attr="infra-refresh"
                    >
                        Refresh
                    </Button>
                </div>
            </div>
            {sources && connected !== sourceNames.length && (
                <p className="alert">
                    Some sources are unavailable or stale. Their rollout state is unverified; inspect Data sources for
                    timestamps.
                </p>
            )}
            {fresh(data.release, now) && data.release?.data?.runs_error && (
                <p className="alert">
                    The version pin is available, but build history is incomplete. Inspect Data sources for details.
                </p>
            )}
            <div className="summary-grid">
                <Card className="summary">
                    <span className="muted">npm latest</span>
                    <strong>{data.package?.data?.version || '…'}</strong>
                    <span className="muted">Published package</span>
                </Card>
                <Card className="summary">
                    <span className="muted">Master pin</span>
                    <strong>
                        {data.release?.data?.pin || (data.release?.status === 'error' ? 'Unavailable' : '…')}
                    </strong>
                    <span className="muted">Target agent version</span>
                </Card>
                <Card className="summary">
                    <span className="muted">Registry coverage</span>
                    <strong>
                        <span>{fresh(data.release, now) ? current : 'Unverified'}</span>
                        {fresh(data.release, now) && <small> / 6 images</small>}
                    </strong>
                    <span className="muted">Version and lineage on both platforms</span>
                </Card>
                <Card className="summary">
                    <span className="muted">Fresh sources</span>
                    <strong>
                        {connected}
                        <small> / {sourceNames.length}</small>
                    </strong>
                    <span className="muted">Registry, GitHub, npm, Postgres and Redis</span>
                </Card>
            </div>
            <nav className="tabs">
                <Button
                    variant={!showSources ? 'secondary' : 'outline'}
                    onClick={() => setShowSources(false)}
                    data-attr="infra-pipeline-tab"
                >
                    Pipeline
                </Button>
                <Button
                    variant={showSources ? 'secondary' : 'outline'}
                    onClick={() => setShowSources(true)}
                    data-attr="infra-sources-tab"
                >
                    Data sources
                </Button>
            </nav>
            {showSources ? (
                <SourceFreshness sources={data} now={now} />
            ) : (
                <div className="workspace">
                    <div className="workspace-main">
                        <ReleasePipeline sources={data} selected={selected} onSelect={setSelected} />
                    </div>
                    <aside id="stage-inspector">
                        <StageInspector
                            selected={selected}
                            sources={data}
                            workflow={workflow}
                            workflowLoading={workflowLoading}
                            onWorkflow={(id) => loadWorkflow({ id })}
                        />
                    </aside>
                    <div className="workspace-inventory">
                        <CustomImageInventory
                            sources={data}
                            inspecting={workflowLoading ? selected : null}
                            onInspect={(id) => {
                                setSelected(id)
                                loadWorkflow({ id })
                                document.getElementById('stage-inspector')?.scrollIntoView({ block: 'nearest' })
                            }}
                        />
                    </div>
                </div>
            )}
            <footer className="page-footer">
                <span>Agent infrastructure · timestamps in UTC</span>
                <span>
                    Current inventory; historical rollout completion and running sandbox versions are not recorded here.
                </span>
            </footer>
        </div>
    )
}
