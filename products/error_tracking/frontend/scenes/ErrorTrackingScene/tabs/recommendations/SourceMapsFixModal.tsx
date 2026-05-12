import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

const FIX_PROMPT = `I'm using PostHog Error Tracking but my JavaScript stack traces are pointing at minified bundles instead of my original source code. Please set up source map uploads for my project so that errors resolve to real file names and line numbers.

Specifically:
1. Detect my bundler (Webpack, Vite, Rollup, esbuild, Next.js, etc.) by inspecting package.json and config files.
2. Install the appropriate PostHog source map upload tooling for that bundler.
3. Wire it into my build pipeline so source maps are uploaded automatically on each production build.
4. Make sure source maps are not shipped to end users (only uploaded to PostHog).
5. Verify the setup by running a build and confirming a symbol set appears in my PostHog project.

Use the existing project configuration where possible and explain any environment variables I need to add (such as the PostHog personal API key).`

export function SourceMapsFixModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }): JSX.Element {
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Fix missing source maps with AI"
            description="Paste the prompt below into your coding agent (Claude Code, Cursor, etc.) and it will wire source map uploads into your build for you."
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        icon={<IconCopy />}
                        onClick={() => copyToClipboard(FIX_PROMPT, 'prompt')}
                    >
                        Copy prompt
                    </LemonButton>
                </>
            }
        >
            <pre className="text-xs bg-surface-secondary border rounded-md p-3 whitespace-pre-wrap font-mono max-h-80 overflow-y-auto m-0">
                {FIX_PROMPT}
            </pre>
        </LemonModal>
    )
}
