import { IconChevronDown } from '@posthog/icons'
import { Button, Heading } from '@posthog/quill'

const FILTERS = ['All sources', 'Any priority', 'Anyone']

export function MockInboxHeader(): JSX.Element {
    return (
        <header className="flex flex-col gap-1">
            <Heading size="xl" render={<h1 />}>
                Inbox
            </Heading>
            <div className="-mx-2 flex flex-wrap items-center">
                {FILTERS.map((filter) => (
                    <Button key={filter} variant="link-muted" size="sm">
                        {filter}
                        <IconChevronDown className="size-3" />
                    </Button>
                ))}
            </div>
        </header>
    )
}
