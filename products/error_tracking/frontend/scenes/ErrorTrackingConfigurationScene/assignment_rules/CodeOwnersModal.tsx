import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

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

const CODE_OWNERS_PLACEHOLDER = 'products/error_tracking/** @team/error-tracking'
const BASE_MODAL_CLASS = 'max-h-[80vh] max-w-[56rem] bg-surface-primary flex flex-col overflow-hidden p-0 gap-0'
const DATE_RANGE_LABELS: Record<string, string> = {
    '-7d': 'Last 7 days',
    '-30d': 'Last 30 days',
    '-90d': 'Last 90 days',
}

function ModalHeader({ title, description }: { title: string; description: string }): JSX.Element {
    return (
        <div className="flex shrink-0 flex-col gap-2 border-b border-primary px-4 py-3 pr-2">
            <DialogTitle className="text-base font-semibold">{title}</DialogTitle>
            <p className="m-0 text-sm text-secondary">{description}</p>
        </div>
    )
}

function ModalFooter({ left, children }: { left?: ReactNode; children: ReactNode }): JSX.Element {
    return (
        <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-primary p-4">
            <div className="min-w-0">{left}</div>
            <div className="flex gap-2 shrink-0">{children}</div>
        </footer>
    )
}

function PasteStep(): JSX.Element {
    const { rawText, hasParsedOwners, unmatchedCount, parseErrors } = useValues(codeOwnersModalLogic)
    const { closeModal, setRawText, goToConfigure } = useActions(codeOwnersModalLogic)
    const hasParseErrors = parseErrors.length > 0

    return (
        <>
            <ModalHeader
                title="Create assignment rules from code owners"
                description="Paste your code owners file. Each owner becomes one assignment rule for exceptions whose source files match its paths."
            />
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
                <CodeEditor
                    className="border rounded"
                    language="codeowners"
                    value={rawText}
                    onChange={(value) => setRawText(value ?? '')}
                    height={420}
                    options={{
                        placeholder: CODE_OWNERS_PLACEHOLDER,
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
            <ModalFooter
                left={
                    <div className="flex flex-col gap-0.5 text-xs text-warning text-left max-h-16 overflow-auto">
                        {parseErrors.slice(0, 4).map((error) => (
                            <span key={error.line}>
                                L{error.line}: {error.reason}
                            </span>
                        ))}
                        {parseErrors.length > 4 && <span>+{parseErrors.length - 4} more</span>}
                    </div>
                }
            >
                <Button variant="outline" onClick={closeModal}>
                    Cancel
                </Button>
                <Button
                    variant="primary"
                    onClick={goToConfigure}
                    disabled={!hasParsedOwners || hasParseErrors}
                    title={
                        hasParseErrors
                            ? 'Fix code owners parsing errors before continuing'
                            : hasParsedOwners
                              ? undefined
                              : 'Paste at least one code owner line'
                    }
                >
                    {unmatchedCount > 0
                        ? `Map ${unmatchedCount} unresolved owner${unmatchedCount === 1 ? '' : 's'}`
                        : 'Review mappings'}
                </Button>
            </ModalFooter>
        </>
    )
}

function ConfigureStep(): JSX.Element {
    const { mappingUnresolvedCount } = useValues(codeOwnersModalLogic)
    const { goToImpact, backToPaste } = useActions(codeOwnersModalLogic)

    return (
        <>
            <ModalHeader
                title="Map unresolved code owners"
                description="Match unresolved owners to a PostHog role or user."
            />
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
                <CodeOwnersConfigureTable />
            </div>
            <ModalFooter
                left={
                    mappingUnresolvedCount > 0 ? (
                        <span className="text-xs text-warning">
                            {mappingUnresolvedCount} owner{mappingUnresolvedCount === 1 ? '' : 's'} still need a PostHog
                            mapping.
                        </span>
                    ) : (
                        <span className="text-xs text-success">All owners are mapped.</span>
                    )
                }
            >
                <Button variant="outline" onClick={backToPaste}>
                    Back
                </Button>
                <Button
                    variant="primary"
                    onClick={goToImpact}
                    disabled={mappingUnresolvedCount > 0}
                    title={
                        mappingUnresolvedCount > 0 ? 'Map every unresolved owner before reviewing impact' : undefined
                    }
                >
                    Review impact
                </Button>
            </ModalFooter>
        </>
    )
}

function ImpactWindowSelect(): JSX.Element {
    const { dateRange } = useValues(codeOwnersModalLogic)
    const { setDateRange } = useActions(codeOwnersModalLogic)

    return (
        <Select value={dateRange} onValueChange={(value) => value && setDateRange(value)}>
            <SelectTrigger id="codeowners-impact-window">
                <SelectValue>{(value: string) => DATE_RANGE_LABELS[value] ?? value}</SelectValue>
            </SelectTrigger>
            <SelectContent>
                {Object.entries(DATE_RANGE_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                        {label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

function ImpactStep(): JSX.Element {
    const { savableRows, savingLoading } = useValues(codeOwnersModalLogic)
    const { backToMapping, saveAll } = useActions(codeOwnersModalLogic)

    return (
        <>
            <ModalHeader
                title="Review assignment rule impact"
                description="Impact is grouped by the PostHog role or user that will receive the generated assignment rules."
            />
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4">
                <CodeOwnersImpactTable />
            </div>
            <ModalFooter left={<ImpactWindowSelect />}>
                <Button variant="outline" onClick={backToMapping}>
                    Back
                </Button>
                <Button
                    variant="primary"
                    onClick={saveAll}
                    loading={savingLoading}
                    disabled={savableRows.length === 0}
                    title={savableRows.length === 0 ? 'No rules with an assignee to save' : undefined}
                >
                    Save {savableRows.length} {savableRows.length === 1 ? 'rule' : 'rules'}
                </Button>
            </ModalFooter>
        </>
    )
}

export function CodeOwnersModal(): JSX.Element {
    const { isOpen, step } = useValues(codeOwnersModalLogic)
    const { closeModal } = useActions(codeOwnersModalLogic)

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && closeModal()}>
            <DialogContent size="wide" className={BASE_MODAL_CLASS}>
                {step === 'paste' && <PasteStep />}
                {step === 'configure' && <ConfigureStep />}
                {step === 'impact' && <ImpactStep />}
            </DialogContent>
        </Dialog>
    )
}
