import { IconWarning } from '@posthog/icons'
import {
    Button,
    Card,
    CardGroup,
    Dialog,
    DialogBody,
    DialogContent,
    DialogHeader,
    DialogTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { METRIC_SOURCE_DOCS_URL, METRIC_SOURCE_OPTIONS } from './useMetricSourceModal'

function SourceCard({
    title,
    description,
    onClick,
    dataAttr,
}: {
    title: string
    description: string
    onClick: () => void
    dataAttr: string
}): JSX.Element {
    return (
        <Card size="sm" className="p-0">
            <button
                type="button"
                className="flex w-full flex-col items-start gap-1 px-3 py-3 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={onClick}
                data-attr={dataAttr}
            >
                <Text size="sm" weight="semibold" render={<span />}>
                    {title}
                </Text>
                <Text size="xs" variant="muted" render={<span />}>
                    {description}
                </Text>
            </button>
        </Card>
    )
}

export function QuillMetricSourceModal({
    isOpen,
    close,
    pickSingleUse,
    pickShared,
    warning,
}: {
    isOpen: boolean
    close: () => void
    pickSingleUse: () => void
    pickShared: () => void
    warning: string | null
}): JSX.Element {
    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && close()}>
            <DialogContent size="wide" className="max-w-2xl" data-attr="experiment-metric-source-modal">
                <DialogHeader>
                    <DialogTitle>Choose metric source</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-3">
                        <CardGroup size="sm" className="grid grid-cols-2 gap-3">
                            <SourceCard
                                {...METRIC_SOURCE_OPTIONS.singleUse}
                                onClick={pickSingleUse}
                                dataAttr="experiment-metric-source-single-use"
                            />
                            <SourceCard
                                {...METRIC_SOURCE_OPTIONS.shared}
                                onClick={pickShared}
                                dataAttr="experiment-metric-source-shared"
                            />
                        </CardGroup>
                        {warning && (
                            <Item variant="outline" size="sm" tone="warning">
                                <ItemMedia variant="icon" aria-hidden>
                                    <IconWarning />
                                </ItemMedia>
                                <ItemContent className="min-w-0">
                                    <ItemDescription className="line-clamp-none">
                                        {warning}
                                        <Button
                                            variant="link"
                                            size="inline"
                                            nativeButton={false}
                                            render={<LinkPrimitive to={METRIC_SOURCE_DOCS_URL} target="_blank" />}
                                        >
                                            Learn more
                                        </Button>
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        )}
                    </div>
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
