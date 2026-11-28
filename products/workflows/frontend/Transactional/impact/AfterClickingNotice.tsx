import { IconSparkles } from '@posthog/icons'

export function AfterClickingNotice({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-start gap-2 border rounded p-3">
            <IconSparkles className="text-lg shrink-0 mt-0.5" />
            <div className="flex flex-col gap-2 items-start flex-1 min-w-0">
                <span className="font-semibold">{title}</span>
                {children}
            </div>
        </div>
    )
}
