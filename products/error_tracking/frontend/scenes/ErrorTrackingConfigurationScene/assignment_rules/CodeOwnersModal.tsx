import { useActions, useValues } from 'kea'

import { CodeEditor } from 'lib/monaco/CodeEditor'
import {
    Button,
    Dialog,
    DialogContent,
    DialogTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from 'lib/ui/quill'

import { CodeOwnersConfigureTable, CodeOwnersImpactTable } from './CodeOwnersConfigureTable'
import { codeOwnersModalLogic } from './codeOwnersModalLogic'

const CODEOWNERS_PLACEHOLDER = 'products/error_tracking/** @posthog/error-tracking'
const BASE_MODAL_CLASS = 'max-h-[80vh] max-w-[56rem] bg-surface-primary flex flex-col overflow-hidden p-0 gap-0'

export function CodeOwnersModal(): JSX.Element {
    const {
        isOpen,
        step,
        rawText,
        savableRows,
        hasParsedOwners,
        saving,
        dateRange,
        unmatchedCount,
        mappingUnresolvedCount,
        parseErrors,
    } = useValues(codeOwnersModalLogic)
    const { closeModal, setRawText, goToConfigure, goToImpact, backToMapping, backToPaste, saveAll, setDateRange } =
        useActions(codeOwnersModalLogic)

    const hasParseErrors = parseErrors.length > 0

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && closeModal()}>
            <DialogContent size="wide" className={BASE_MODAL_CLASS}>
                {step === 'paste' && (
                    <>
                        <div className="flex shrink-0 flex-col gap-2 border-b border-primary px-4 py-3 pr-2">
                            <div className="flex items-start justify-between gap-2">
                                <DialogTitle className="min-w-0 flex-1 text-base font-semibold">
                                    Create assignment rules from code owners
                                </DialogTitle>
                            </div>
                            <p className="m-0 text-sm text-secondary">
                                Paste your CODEOWNERS file. Each owner becomes one assignment rule for exceptions whose
                                source files match its paths.
                            </p>
                        </div>
                        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
                            <div className="relative">
                                <CodeEditor
                                    className="border rounded"
                                    language="codeowners"
                                    value={rawText}
                                    onChange={(value) => setRawText(value ?? '')}
                                    height={420}
                                    options={{
                                        placeholder: CODEOWNERS_PLACEHOLDER,
                                        minimap: { enabled: false },
                                        scrollBeyondLastLine: false,
                                        wordWrap: 'on',
                                        lineNumbers: 'on',
                                        folding: false,
                                        lineDecorationsWidth: 8,
                                        lineNumbersMinChars: 2,
                                        fontSize: 12,
                                        renderLineHighlight: 'none',
                                    }}
                                />
                            </div>
                        </div>
                        <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-primary p-4">
                            <div className="flex flex-col gap-0.5 text-xs text-warning text-left max-h-16 overflow-auto">
                                {parseErrors.slice(0, 4).map((error) => (
                                    <span key={error.line}>
                                        Line {error.line}: {error.reason}
                                    </span>
                                ))}
                                {parseErrors.length > 4 && <span>+{parseErrors.length - 4} more</span>}
                            </div>
                            <div className="flex gap-2 shrink-0">
                                <Button variant="outline" onClick={closeModal}>
                                    Cancel
                                </Button>
                                <Button
                                    variant="primary"
                                    onClick={goToConfigure}
                                    disabled={!hasParsedOwners || hasParseErrors}
                                    title={
                                        hasParseErrors
                                            ? 'Fix CODEOWNERS parsing errors before continuing'
                                            : hasParsedOwners
                                              ? undefined
                                              : 'Paste at least one code owner line'
                                    }
                                >
                                    {unmatchedCount > 0
                                        ? `Map ${unmatchedCount} unresolved owner${unmatchedCount === 1 ? '' : 's'}`
                                        : 'Review mappings'}
                                </Button>
                            </div>
                        </footer>
                    </>
                )}

                {step === 'configure' && (
                    <>
                        <div className="flex shrink-0 flex-col gap-2 border-b border-primary px-4 py-3 pr-2">
                            <div className="flex items-start justify-between gap-2">
                                <DialogTitle className="min-w-0 flex-1 text-base font-semibold">
                                    Map unresolved code owners
                                </DialogTitle>
                            </div>
                            <p className="m-0 text-sm text-secondary">
                                Match unresolved GitHub handles to a PostHog role or user.
                            </p>
                        </div>
                        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
                            <div className="flex flex-col gap-3">
                                <CodeOwnersConfigureTable />
                            </div>
                        </div>
                        <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-primary p-4">
                            {mappingUnresolvedCount > 0 ? (
                                <span className="text-xs text-warning">
                                    {mappingUnresolvedCount} GitHub handle{mappingUnresolvedCount === 1 ? '' : 's'}{' '}
                                    still need a PostHog mapping.
                                </span>
                            ) : (
                                <span className="text-xs text-success">All GitHub handles are mapped.</span>
                            )}
                            <div className="flex gap-2 shrink-0">
                                <>
                                    <Button variant="outline" onClick={backToPaste}>
                                        Back
                                    </Button>
                                    <Button
                                        variant="primary"
                                        onClick={goToImpact}
                                        disabled={mappingUnresolvedCount > 0}
                                        title={
                                            mappingUnresolvedCount > 0
                                                ? 'Map every unresolved GitHub handle before reviewing impact'
                                                : undefined
                                        }
                                    >
                                        Review impact
                                    </Button>
                                </>
                            </div>
                        </footer>
                    </>
                )}

                {step === 'impact' && (
                    <>
                        <div className="flex shrink-0 flex-col gap-2 border-b border-primary px-4 py-3 pr-2">
                            <div className="flex items-start justify-between gap-2">
                                <DialogTitle className="min-w-0 flex-1 text-base font-semibold">
                                    Review assignment rule impact
                                </DialogTitle>
                            </div>
                            <p className="m-0 text-sm text-secondary">
                                Impact is grouped by the PostHog role or user that will receive the generated assignment
                                rules.
                            </p>
                        </div>
                        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
                            <CodeOwnersImpactTable />
                        </div>
                        <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-primary p-4">
                            <Select value={dateRange} onValueChange={(value) => value && setDateRange(value)}>
                                <SelectTrigger id="codeowners-impact-window">
                                    <SelectValue>
                                        {(value: string) =>
                                            value === '-7d'
                                                ? 'Last 7 days'
                                                : value === '-30d'
                                                  ? 'Last 30 days'
                                                  : 'Last 90 days'
                                        }
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="-7d">Last 7 days</SelectItem>
                                    <SelectItem value="-30d">Last 30 days</SelectItem>
                                    <SelectItem value="-90d">Last 90 days</SelectItem>
                                </SelectContent>
                            </Select>
                            <div className="flex gap-2 shrink-0">
                                <Button variant="outline" onClick={backToMapping}>
                                    Back
                                </Button>
                                <Button
                                    variant="primary"
                                    onClick={saveAll}
                                    loading={saving}
                                    disabled={savableRows.length === 0}
                                    title={savableRows.length === 0 ? 'No rules with an assignee to save' : undefined}
                                >
                                    Save {savableRows.length} {savableRows.length === 1 ? 'rule' : 'rules'}
                                </Button>
                            </div>
                        </footer>
                    </>
                )}
            </DialogContent>
        </Dialog>
    )
}
