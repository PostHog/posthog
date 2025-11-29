import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'

export const KeyboardShortcuts = (): JSX.Element => (
    <>
        <KeyboardShortcut arrowup />
        <KeyboardShortcut arrowdown />
        <span className="mx-1 text-muted">or</span>
        <KeyboardShortcut j />
        <KeyboardShortcut k />
        <span className="text-muted">navigate</span>
        <span className="mx-1">·</span>
        <KeyboardShortcut enter />
        <span className="text-muted">expand</span>
    </>
)
