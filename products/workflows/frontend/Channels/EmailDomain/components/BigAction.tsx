import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

export function BigAction({ children, ...props }: LemonButtonProps): JSX.Element {
    return (
        <LemonButton type="primary" size="large" fullWidth center className="text-base" {...props}>
            {children}
        </LemonButton>
    )
}
