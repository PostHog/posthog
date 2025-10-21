import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { StateInspector } from 'products/live_debugger/frontend/StateInspector'

import { BreakpointInstance, liveDebuggerLogic } from './liveDebuggerLogic'
import { RepositoryBrowser } from './repo_browser/RepositoryBrowser'

export const scene: SceneExport = {
    component: LiveDebugger,
    logic: liveDebuggerLogic,
}

function BreakpointInstanceCard({
    instance,
    isSelected,
    isNew,
    onClick,
}: {
    instance: BreakpointInstance
    isSelected: boolean
    isNew: boolean
    onClick: () => void
}): JSX.Element {
    return (
        <div
            className={clsx(
                'p-2 border rounded cursor-pointer transition-colors text-xs',
                isSelected ? 'border-primary bg-primary-highlight' : 'border-border hover:bg-bg-light',
                isNew && 'animate-pulse bg-warning-highlight border-warning'
            )}
            onClick={onClick}
        >
            <div className="text-muted text-xs mb-0.5">{dayjs(instance.timestamp).fromNow()}</div>
            <div
                className="font-mono font-semibold text-xs truncate"
                title={`${instance.functionName || 'captureEvent'}:${instance.lineNumber}`}
            >
                {instance.functionName || 'captureEvent'}:{instance.lineNumber}
            </div>
        </div>
    )
}

export function LiveDebugger(): JSX.Element {
    const isEnabled = useFeatureFlag('LIVE_DEBUGGER')

    const { selectedInstance, newInstanceIds, selectedLineForHits, hitsForSelectedLine } = useValues(liveDebuggerLogic)
    const { selectInstance, showHitsForLine } = useActions(liveDebuggerLogic)

    if (!isEnabled) {
        return <NotFound object="Live debugger" caption="This feature is not enabled for your project." />
    }

    return (
        <>
            <SceneTitleSection
                name="Live Debugger"
                description="Set breakpoints in your code to capture and inspect runtime values"
                resourceType={{
                    type: 'live_debugger',
                }}
            />

            <SceneDivider />

            <SceneContent>
                <div className="flex gap-3 h-[calc(100vh-200px)]">
                    <RepositoryBrowser />

                    {/* Middle - Breakpoint instances for selected line */}
                    <div className="w-64 border rounded bg-bg-light overflow-hidden flex flex-col">
                        <div className="px-2 py-1.5 border-b bg-bg-3000 flex items-center justify-between">
                            <span className="font-semibold text-xs">
                                {selectedLineForHits ? `Line ${selectedLineForHits}` : 'Hits'}
                            </span>
                            {selectedLineForHits && (
                                <button
                                    onClick={() => showHitsForLine(null)}
                                    className="text-xs text-muted hover:text-default"
                                >
                                    Clear
                                </button>
                            )}
                        </div>

                        <div className="flex-1 overflow-auto">
                            {selectedLineForHits ? (
                                hitsForSelectedLine.length > 0 ? (
                                    <div className="p-1.5 space-y-1.5">
                                        {hitsForSelectedLine.map((instance) => (
                                            <BreakpointInstanceCard
                                                key={instance.id}
                                                instance={instance}
                                                isSelected={selectedInstance?.id === instance.id}
                                                isNew={newInstanceIds.has(instance.id)}
                                                onClick={() => selectInstance(instance.id)}
                                            />
                                        ))}
                                    </div>
                                ) : (
                                    <div className="flex-1 flex items-center justify-center text-muted p-2 text-center">
                                        <p className="text-xs">No hits</p>
                                    </div>
                                )
                            ) : (
                                <div className="flex-1 flex items-center justify-center text-muted p-2 text-center">
                                    <div className="text-xs">
                                        <p>Click hit count badges</p>
                                        <p className="mt-1">to view hits</p>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    {selectedInstance && (
                        <StateInspector selectedInstance={selectedInstance} selectInstance={selectInstance} />
                    )}
                </div>
            </SceneContent>
        </>
    )
}
