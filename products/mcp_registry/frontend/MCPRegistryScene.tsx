import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { Candidate } from './Candidate'
import { mcpRegistryLogic } from './mcpRegistryLogic'

export const scene: SceneExport = {
    component: MCPRegistryScene,
    logic: mcpRegistryLogic,
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
