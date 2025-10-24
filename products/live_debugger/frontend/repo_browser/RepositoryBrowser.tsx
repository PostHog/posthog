import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTree } from 'lib/lemon-ui/LemonTree/LemonTree'

import { CodeLine } from '../CodeLine'
import { liveDebuggerLogic } from '../liveDebuggerLogic'
import { repoBrowserLogic } from './repoBrowserLogic'

export function RepositoryBrowser(): JSX.Element {
    const { fileSearchQuery, repositoryTreeLoading, treeData, codeLines, selectedFilePath } =
        useValues(repoBrowserLogic)

    const { loadFileContent, setFileSearchQuery } = useActions(repoBrowserLogic)

    const { breakpoints, breakpointsByLine, instancesByLine, hitCountsByLine, newHitsByLine, currentRepository } =
        useValues(liveDebuggerLogic)

    const { clearAllBreakpoints, toggleBreakpoint, showHitsForLine, setSelectedFilePath } =
        useActions(liveDebuggerLogic)

    return (
        <>
            <div className="flex-1 border rounded bg-bg-light overflow-hidden flex flex-col">
                <div className="p-2 border-b bg-bg-3000">
                    <span className="font-semibold">Files</span>
                </div>
                <div className="p-2 border-b">
                    <LemonInput
                        type="search"
                        placeholder="Search files..."
                        value={fileSearchQuery}
                        onChange={(value) => setFileSearchQuery(value)}
                        fullWidth
                    />
                </div>
                <div className="flex-1 overflow-auto">
                    {repositoryTreeLoading ? (
                        <div className="p-4 text-center text-muted">Loading repository...</div>
                    ) : treeData.length === 0 ? (
                        <div className="p-4 text-center text-muted">
                            {fileSearchQuery ? 'No files found' : 'No Python files in repository'}
                        </div>
                    ) : (
                        <LemonTree
                            data={treeData}
                            onFolderClick={() => {}}
                            onItemClick={(item) => {
                                if (item?.record?.type === 'file') {
                                    loadFileContent(item.record.fullPath)
                                    setSelectedFilePath(item.record.fullPath)
                                }
                            }}
                        />
                    )}
                </div>
            </div>

            <div className="flex-[2] border rounded bg-bg-light overflow-hidden flex flex-col">
                <div className="flex items-center justify-between p-2 border-b bg-bg-3000">
                    <span className="font-semibold">{selectedFilePath ? selectedFilePath : 'Code'}</span>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={clearAllBreakpoints}
                        disabled={!breakpoints || breakpoints.length === 0}
                    >
                        Clear all breakpoints
                    </LemonButton>
                </div>
                <div className="flex-1 overflow-auto font-mono text-xs">
                    {!codeLines ? (
                        <div className="flex items-center justify-center h-full text-muted p-4 text-center">
                            <p>Select a file from the file browser to view its contents and set breakpoints</p>
                        </div>
                    ) : (
                        codeLines.map((line, index) => {
                            const lineNumber = index + 1
                            const hasBreakpoint = !!breakpointsByLine[lineNumber]
                            const hasInstances = !!instancesByLine[lineNumber]?.length
                            const hitCount = hitCountsByLine[lineNumber] || 0
                            const hasNewHits = newHitsByLine.has(lineNumber)

                            return (
                                <CodeLine
                                    key={index}
                                    line={line}
                                    lineNumber={lineNumber}
                                    hasBreakpoint={hasBreakpoint}
                                    hasInstances={hasInstances}
                                    hitCount={hitCount}
                                    hasNewHits={hasNewHits}
                                    onClick={() => {
                                        if (selectedFilePath) {
                                            toggleBreakpoint(selectedFilePath, lineNumber, currentRepository)
                                        }
                                    }}
                                    onHitCountClick={() => showHitsForLine(lineNumber)}
                                />
                            )
                        })
                    )}
                </div>
            </div>
        </>
    )
}
