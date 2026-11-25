import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
} from '@posthog/quill'

import { CodeEditor } from 'lib/monaco/CodeEditor'

import { CodeOwnersImpactTable } from './CodeOwnersConfigureTable'
import { codeOwnersModalLogic } from './codeOwnersModalLogic'
import { QuillCodeOwnersConfigureTable } from './QuillCodeOwnersConfigureTable'

const CODE_OWNERS_PLACEHOLDER = 'products/error_tracking/** @team/error-tracking'
const DATE_RANGE_LABELS: Record<string, string> = {
    '-7d': 'Last 7 days',
    '-30d': 'Last 30 days',
    '-90d': 'Last 90 days',
}

function StepHeader({ title, description }: { title: string; description: string }): JSX.Element {
    return (
        <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
    )
}

function StepFooter({ left, children }: { left?: ReactNode; children: ReactNode }): JSX.Element {
    return (
        <DialogFooter className="flex-wrap items-center sm:justify-between">
            <div className="min-w-0">{left}</div>
            <div className="flex shrink-0 flex-wrap gap-2">{children}</div>
        </DialogFooter>
    )
}

function PasteStep(): JSX.Element {
    const { rawText, hasParsedOwners, unmatchedCount, parseErrors } = useValues(codeOwnersModalLogic)
    const { closeModal, setRawText, goToConfigure } = useActions(codeOwnersModalLogic)
    const hasParseErrors = parseErrors.length > 0

    return (
        <>
            <StepHeader
                title="Create assignment rules from code owners"
                description="Paste your code owners file. Each owner becomes one assignment rule for exceptions whose source files match its paths."
            />
            <DialogBody>
                <CodeEditor
                    className="rounded-md border border-border"
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
            </DialogBody>
            <StepFooter
                left={
                    hasParseErrors ? (
                        <div className="flex max-h-16 flex-col gap-0.5 overflow-auto text-left">
                            {parseErrors.slice(0, 4).map((error) => (
                                <Text
                                    key={error.line}
                                    size="xs"
                                    className="m-0 text-warning-foreground"
                                    render={<span />}
                                >
                                    L{error.line}: {error.reason}
                                </Text>
                            ))}
                            {parseErrors.length > 4 && (
                                <Text size="xs" className="m-0 text-warning-foreground" render={<span />}>
                                    +{parseErrors.length - 4} more
                                </Text>
                            )}
                        </div>
                    ) : null
                }
            >
                <Button variant="outline" onClick={closeModal}>
                    Cancel
                </Button>
                <Button
                    variant="primary"
                    onClick={goToConfigure}
                    disabledReason={
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
            </StepFooter>
        </>
    )
}

function ConfigureStep(): JSX.Element {
    const { mappingUnresolvedCount } = useValues(codeOwnersModalLogic)
    const { goToImpact, backToPaste } = useActions(codeOwnersModalLogic)

    return (
        <>
            <StepHeader
                title="Map unresolved code owners"
                description="Match unresolved owners to a PostHog role or user."
            />
            <DialogBody>
                <QuillCodeOwnersConfigureTable />
            </DialogBody>
            <StepFooter
                left={
                    mappingUnresolvedCount > 0 ? (
                        <Text size="xs" className="m-0 text-warning-foreground" render={<span />}>
                            {mappingUnresolvedCount} owner{mappingUnresolvedCount === 1 ? '' : 's'} still need a PostHog
                            mapping.
                        </Text>
                    ) : (
                        <Text size="xs" className="m-0 text-success-foreground" render={<span />}>
                            All owners are mapped.
                        </Text>
                    )
                }
            >
                <Button variant="outline" onClick={backToPaste}>
                    Back
                </Button>
                <Button
                    variant="primary"
                    onClick={goToImpact}
                    disabledReason={
                        mappingUnresolvedCount > 0 ? 'Map every unresolved owner before reviewing impact' : undefined
                    }
                >
                    Review impact
                </Button>
            </StepFooter>
        </>
    )
}

function ImpactWindowSelect(): JSX.Element {
    const { dateRange } = useValues(codeOwnersModalLogic)
    const { setDateRange } = useActions(codeOwnersModalLogic)

    return (
        <Select value={dateRange} onValueChange={(value) => value && setDateRange(value)}>
            <SelectTrigger id="codeowners-impact-window" aria-label="Impact window">
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
            <StepHeader
                title="Review assignment rule impact"
                description="Impact is grouped by the PostHog role or user that will receive the generated assignment rules."
            />
            <DialogBody>
                <CodeOwnersImpactTable />
            </DialogBody>
            <StepFooter left={<ImpactWindowSelect />}>
                <Button variant="outline" onClick={backToMapping}>
                    Back
                </Button>
                <Button
                    variant="primary"
                    onClick={saveAll}
                    loading={savingLoading}
                    disabledReason={savableRows.length === 0 ? 'No rules with an assignee to save' : undefined}
                >
                    Save {savableRows.length} {savableRows.length === 1 ? 'rule' : 'rules'}
                </Button>
            </StepFooter>
        </>
    )
}

export function QuillCodeOwnersModal(): JSX.Element {
    const { isOpen, step } = useValues(codeOwnersModalLogic)
    const { closeModal } = useActions(codeOwnersModalLogic)

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && closeModal()}>
            <DialogContent size="wide">
                {step === 'paste' && <PasteStep />}
                {step === 'configure' && <ConfigureStep />}
                {step === 'impact' && <ImpactStep />}
            </DialogContent>
        </Dialog>
    )
}
