import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'

import { JSONViewer } from 'lib/components/JSONViewer'

import { LemonButton } from '../../../frontend/src/lib/lemon-ui/LemonButton'
import { liveDebuggerLogic } from './liveDebuggerLogic'
import { parseJsonPickleVariable } from './serde'

function VariableDisplay({ variables }: { variables: Record<string, any> }): JSX.Element {
    return (
        <div className="border rounded divide-y">
            {Object.entries(variables).map(([key, value]) => {
                const parsed = parseJsonPickleVariable(value)
                return (
                    <div key={key} className="p-2">
                        <div className="flex items-center gap-2 mb-1">
                            <div className="text-muted text-xs font-semibold">{key}</div>
                            {parsed.typeName && (
                                <div className="text-xs text-muted-alt bg-bg-3000 px-1.5 py-0.5 rounded font-mono">
                                    {parsed.typeName}
                                </div>
                            )}
                        </div>
                        <div className="text-xs font-mono break-words">
                            {parsed.type === 'complex' ? (
                                <JSONViewer src={parsed.value} collapsed={1} />
                            ) : (
                                <span>{String(parsed.value)}</span>
                            )}
                        </div>
                    </div>
                )
            })}
        </div>
    )
}

export function StateInspector({
    selectedInstance,
    selectInstance,
}: {
    selectedInstance: any
    selectInstance: (arg: any) => void
}): JSX.Element {
    const { breakpoints, breakpointInstances, currentRepository } = useValues(liveDebuggerLogic)

    const { toggleBreakpointForFile } = useActions(liveDebuggerLogic)

    return (
        <div className="flex-[2] border rounded bg-bg-light overflow-hidden flex flex-col">
            <div className="flex items-center justify-between p-2 border-b bg-bg-3000">
                <span className="font-semibold">Debug Details</span>
                <button onClick={() => selectInstance(null)} className="text-muted hover:text-default">
                    <IconX />
                </button>
            </div>

            <div className="flex-1 p-3 overflow-auto space-y-4">
                <div>
                    <h4 className="font-semibold text-sm mb-2">Variables at Line {selectedInstance.lineNumber}</h4>
                    <VariableDisplay variables={selectedInstance.variables} />
                </div>

                {selectedInstance.stackTrace && (
                    <div>
                        <h4 className="font-semibold text-sm mb-2">Stack Trace</h4>
                        <div className="text-xs font-mono bg-bg-3000 p-2 rounded max-h-96 overflow-auto space-y-1">
                            {selectedInstance.stackTrace.map((frame: any, i: number) => {
                                const functionName = frame[1]
                                const fileName = frame[0]
                                const lineNumber = frame[2] as number

                                // Match filenames more flexibly (handle full paths vs relative paths)
                                const fileNameMatch = (bpFilename: string, stackFilename: string): boolean => {
                                    if (bpFilename === stackFilename) {
                                        return true
                                    }
                                    // Check if one ends with the other (handles full path vs relative)
                                    return bpFilename.endsWith(stackFilename) || stackFilename.endsWith(bpFilename)
                                }

                                const hasBreakpoint =
                                    Array.isArray(breakpoints) &&
                                    breakpoints.some(
                                        (bp) => fileNameMatch(bp.filename, fileName) && bp.line_number === lineNumber
                                    )
                                const hitCount = Array.isArray(breakpointInstances)
                                    ? breakpointInstances.filter(
                                          (inst) =>
                                              fileNameMatch(inst.filename, fileName) && inst.lineNumber === lineNumber
                                      ).length
                                    : 0

                                return (
                                    <div
                                        key={i}
                                        className="px-2 py-1 border border-border rounded hover:bg-bg-light flex items-center justify-between gap-2"
                                    >
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-baseline gap-1.5">
                                                <span className="text-muted font-normal">#{i}</span>
                                                <span className="font-semibold truncate">{functionName}</span>
                                                {hitCount > 0 && (
                                                    <span className="text-xs bg-orange-500 text-white px-1 rounded">
                                                        {hitCount}
                                                    </span>
                                                )}
                                            </div>
                                            <div className="text-muted text-xs truncate">
                                                {fileName}
                                                {lineNumber ? `:${lineNumber}` : ''}
                                            </div>
                                        </div>
                                        {lineNumber && (
                                            <LemonButton
                                                size="xsmall"
                                                type={hasBreakpoint ? 'primary' : 'secondary'}
                                                onClick={() => {
                                                    if (typeof lineNumber === 'number') {
                                                        toggleBreakpointForFile(fileName, lineNumber, currentRepository)
                                                    }
                                                }}
                                            >
                                                BP
                                            </LemonButton>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
