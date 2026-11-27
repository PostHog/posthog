import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { InstrumentationFix } from '../instrumentationFixes'
import { FixWithAgentButton } from './FixWithAgentButton'

export function InstrumentationEmptyState({
    fix,
    dataAttr,
}: {
    fix: InstrumentationFix
    dataAttr: string
}): JSX.Element {
    return (
        <Empty className="border-none px-4 py-6">
            <EmptyHeader>
                <EmptyTitle>{fix.emptyState?.title}</EmptyTitle>
                <EmptyDescription>{fix.emptyState?.detail}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent className="flex-row flex-wrap justify-center">
                <FixWithAgentButton fix={fix} size="sm" dataAttr={`${dataAttr}-fix`} />
                <Button
                    variant="outline"
                    size="sm"
                    render={<LinkPrimitive to={fix.docsUrl} target="_blank" />}
                    data-attr={`${dataAttr}-docs`}
                >
                    Docs
                </Button>
            </EmptyContent>
        </Empty>
    )
}
