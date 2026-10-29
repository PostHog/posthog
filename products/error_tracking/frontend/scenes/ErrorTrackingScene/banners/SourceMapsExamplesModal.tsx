import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconExternal, IconMagicWand } from '@posthog/icons'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Text,
} from 'lib/ui/quill'

import { SourceMapsExamplesBrowser } from './SourceMapsExamplesBrowser'
import { sourceMapsExamplesLogic } from './sourceMapsExamplesLogic'
import { SOURCE_MAPS_DOCS_URL, SOURCE_MAPS_PLATFORM_LABELS, sourceMapsFixWizardLogic } from './sourceMapsFixWizardLogic'

export function SourceMapsExamplesModal(): JSX.Element {
    const { isOpen, platform, examples, examplesLoading, examplesFailed, selectedExampleIndex } =
        useValues(sourceMapsExamplesLogic)
    const { closeExamples, loadExamples, selectExample } = useActions(sourceMapsExamplesLogic)
    const { openModal } = useActions(sourceMapsFixWizardLogic)
    const wizardRef = useRef<HTMLButtonElement>(null)
    const labels = SOURCE_MAPS_PLATFORM_LABELS[platform ?? 'javascript']
    const lookbackHours = examples?.lookback_hours ?? 24
    const retry = (): void => {
        if (platform) {
            loadExamples(platform)
        }
    }

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && closeExamples()}>
            <DialogContent size="wide" initialFocus={wizardRef}>
                <DialogHeader>
                    <DialogTitle>{`${labels.platform} frames missing ${labels.symbols}`}</DialogTitle>
                    <DialogDescription>
                        {`The files and builds with the most frames missing ${labels.symbols} in the last ${lookbackHours} hours.`}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    {examplesLoading || (examples === null && !examplesFailed) ? (
                        <div className="flex flex-col gap-2">
                            <Skeleton className="h-12" />
                            <Skeleton className="h-12" />
                            <Skeleton className="h-12" />
                        </div>
                    ) : examplesFailed || !examples ? (
                        <Text size="xs" variant="destructive">
                            Couldn't load the examples. If it keeps failing, contact support.{' '}
                            <Button variant="link" size="inline" onClick={retry}>
                                Try again
                            </Button>
                        </Text>
                    ) : examples.results.length === 0 ? (
                        <Empty>
                            <EmptyHeader>
                                <EmptyTitle>{`No frames are missing ${labels.symbols}`}</EmptyTitle>
                                <EmptyDescription>
                                    {`Nothing to upload from the last ${lookbackHours} hours.`}
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    ) : (
                        <SourceMapsExamplesBrowser
                            examples={examples}
                            selectedIndex={selectedExampleIndex}
                            onSelect={selectExample}
                            onRetry={retry}
                            onOpenException={closeExamples}
                        />
                    )}
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" render={<LinkPrimitive to={SOURCE_MAPS_DOCS_URL} target="_blank" />}>
                        Read docs
                        <IconExternal />
                    </Button>
                    <Button
                        ref={wizardRef}
                        variant="primary"
                        onClick={() => {
                            closeExamples()
                            openModal('source_maps_examples')
                        }}
                        data-attr="error-tracking-source-maps-examples-wizard"
                    >
                        <IconMagicWand />
                        Fix with Wizard
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
