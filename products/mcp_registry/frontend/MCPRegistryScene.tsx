import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonTag, Spinner } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { MCPDiscoverCandidateApi, MCPDiscoverCandidateApiMeasured } from './generated/api.schemas'
import { mcpRegistryLogic } from './mcpRegistryLogic'

export const scene: SceneExport = {
    component: MCPRegistryScene,
    logic: mcpRegistryLogic,
}

type LivenessLabel = { label: string; type: 'success' | 'warning' | 'danger' | 'muted' | 'default' }

/** Probe states are internal keys. People need to know whether the server answers. */
const LIVENESS: Record<string, LivenessLabel> = {
    alive_open: { label: 'Live, no sign-in', type: 'success' },
    alive_auth: { label: 'Live, needs sign-in', type: 'success' },
    alive_protocol: { label: 'Responds', type: 'default' },
    package_only: { label: 'Runs locally', type: 'muted' },
    unprobed: { label: 'Not checked yet', type: 'muted' },
    not_mcp: { label: 'Not an MCP server', type: 'warning' },
    dead: { label: 'Not responding', type: 'danger' },
}

function numberFrom(measured: MCPDiscoverCandidateApiMeasured, key: string): number | null {
    const value = measured?.[key]
    return typeof value === 'number' ? value : null
}

function MeasuredTag({ measured }: { measured: MCPDiscoverCandidateApiMeasured }): JSX.Element | null {
    const calls = numberFrom(measured, 'calls')
    if (calls === null) {
        return null
    }
    const errorRate = numberFrom(measured, 'error_rate_pct')
    const success = errorRate === null ? null : `${(100 - errorRate).toFixed(1)}% success`
    return (
        <LemonTag type="highlight">
            {calls.toLocaleString()} real calls{success ? `, ${success}` : ''}
        </LemonTag>
    )
}

function Candidate({ candidate }: { candidate: MCPDiscoverCandidateApi }): JSX.Element {
    const liveness = LIVENESS[candidate.liveness] ?? { label: candidate.liveness, type: 'muted' as const }
    return (
        <li className="border rounded p-3 flex flex-col gap-1">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-muted tabular-nums">{candidate.rank}</span>
                <span className="font-semibold">{candidate.title}</span>
                <LemonTag type={liveness.type}>{liveness.label}</LemonTag>
                <MeasuredTag measured={candidate.measured} />
            </div>
            {candidate.registry_name ? (
                <code className="text-xs text-muted break-all">{candidate.registry_name}</code>
            ) : null}
            {candidate.description ? <p className="m-0 text-sm">{candidate.description}</p> : null}
            {candidate.matched_tools.length > 0 ? (
                <div className="flex gap-1 flex-wrap">
                    {candidate.matched_tools.map((tool) => (
                        <LemonTag key={tool.name} type="option">
                            {tool.name}
                        </LemonTag>
                    ))}
                </div>
            ) : null}
        </li>
    )
}

export function MCPRegistryScene(): JSX.Element {
    const { intent, candidates, responseLoading, searchError, searchedIntent } = useValues(mcpRegistryLogic)
    const { setIntent, search } = useActions(mcpRegistryLogic)

    return (
        <SceneContent>
            <div className="flex flex-col gap-4 max-w-3xl w-full mx-auto">
                <div className="flex flex-col gap-2">
                    <h1 className="m-0">Find an MCP server</h1>
                    <p className="m-0 text-muted">
                        Describe what you want to do. Servers are ranked by whether they answer right now and by how
                        well they work for the agents already calling them.
                    </p>
                </div>

                <form
                    className="flex gap-2"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (!responseLoading) {
                            search()
                        }
                    }}
                >
                    <LemonInput
                        className="flex-1"
                        value={intent}
                        onChange={setIntent}
                        placeholder="Deploy my site to Vercel"
                        autoFocus
                        data-attr="mcp-registry-search"
                    />
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={responseLoading}
                        disabledReason={!intent.trim() ? 'Describe what you want to do' : undefined}
                    >
                        Search
                    </LemonButton>
                </form>

                {searchError && !responseLoading ? (
                    <LemonBanner type="error">
                        Search failed: {searchError}. Check the connection and try again.
                    </LemonBanner>
                ) : null}

                {responseLoading ? (
                    <Spinner className="self-center text-2xl" />
                ) : candidates.length > 0 ? (
                    <>
                        {/* The box can be edited without resubmitting, so name the query these results answer. */}
                        <p className="m-0 text-muted text-sm">Results for “{searchedIntent}”</p>
                        <ul className="list-none p-0 m-0 flex flex-col gap-2">
                            {candidates.map((candidate) => (
                                <Candidate key={candidate.id} candidate={candidate} />
                            ))}
                        </ul>
                    </>
                ) : searchedIntent ? (
                    <p className="text-muted">
                        Nothing matched “{searchedIntent}”. Search looks for the words a server uses about itself, so
                        try the vendor or product name.
                    </p>
                ) : null}
            </div>
        </SceneContent>
    )
}
