import type { ReactNode } from 'react'

export function SetupStepLayout({ children, aside }: { children: ReactNode; aside: ReactNode }): JSX.Element {
    return (
        <div className="grid items-start gap-8 @min-[56rem]/setup-mode:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] @min-[72rem]/setup-mode:gap-12">
            <div className="flex min-w-0 flex-col gap-6">{children}</div>
            <aside className="flex min-w-0 flex-col gap-4">{aside}</aside>
        </div>
    )
}
