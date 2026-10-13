import { LemonCard } from 'lib/lemon-ui/LemonCard'

export function SettingsList({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="divide-y divide-primary overflow-hidden p-0">
            {children}
        </LemonCard>
    )
}
