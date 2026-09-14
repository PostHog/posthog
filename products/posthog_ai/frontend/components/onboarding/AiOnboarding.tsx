import { Suspense } from 'react'

import { lazyWithRetry } from 'lib/utils/retryImport'

import type { AiOnboardingProps } from './AiOnboardingImpl'

export type { AiOnboardingProps } from './AiOnboardingImpl'

// The takeover pulls quill's dialog chunk, the step manifest and the media leaf. Its host (`GlobalModals`)
// is downloaded on every logged-in page, so the impl is reached only through this dynamic `import()` — the
// type import above is erased, so the chunk genuinely splits. There's no fallback UI: a modal that hasn't
// loaded yet should show nothing rather than flash a skeleton over the page.
const Lazy = lazyWithRetry(() => import('./AiOnboardingImpl').then((m) => ({ default: m.AiOnboarding })))

/**
 * The PostHog AI onboarding takeover, code-split. Renders nothing until the host marks the user eligible
 * (`autoOpen`) or the replay button opens it.
 */
export function AiOnboarding(props: AiOnboardingProps): JSX.Element {
    return (
        <Suspense fallback={null}>
            <Lazy {...props} />
        </Suspense>
    )
}
