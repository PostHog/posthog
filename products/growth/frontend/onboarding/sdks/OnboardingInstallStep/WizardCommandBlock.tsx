import './WizardCommandBlock.scss'

import { useState } from 'react'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { cn } from 'lib/utils/css-classes'

import { useWizardCommand } from '../sdk-install-instructions/components/SetupWizardBanner'

// Supported wizard frameworks for display
const WIZARD_FRAMEWORKS = [
    'Next.js',
    'React',
    'Angular',
    'Vue',
    'Nuxt',
    'Astro',
    'SvelteKit',
    'Django',
    'Flask',
    'Laravel',
    'React Native',
    'iOS',
    'Android',
    'Ruby on Rails',
    'React Router',
    'Python',
]

const WIZARD_HOG_URL = 'https://res.cloudinary.com/dmukukwp6/image/upload/wizard_3f8bb7a240.png'

export function WizardCommandBlock(): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const [castKey, setCastKey] = useState(0)

    // The `npx @posthog/wizard` CLI only targets cloud (US/EU) and dev instances —
    // self-hosted deployments have no preconfigured endpoint, so we hide the block
    // entirely rather than show a command that can't work. Matches SetupWizardBanner.
    if (!isCloudOrDev) {
        return <></>
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex gap-6">
                <img
                    key={`hog-${castKey}`}
                    src={WIZARD_HOG_URL}
                    alt="PostHog wizard hedgehog"
                    className={cn(
                        'w-28 h-28 hidden sm:block shrink-0 self-center',
                        castKey > 0 && 'WizardCommandBlock__hogCast'
                    )}
                />
                <div className="flex-1 flex flex-col gap-3">
                    <CommandBlock
                        command={wizardCommand}
                        copyLabel="Wizard command"
                        ariaLabel="Copy wizard command"
                        size="md"
                        decoration="rainbow"
                        className="bg-bg-light border border-border hover:border-primary"
                        onCopy={(key) => setCastKey(key)}
                    />

                    <p className="text-xs text-muted mb-0">
                        Auto-detects your framework, installs the SDK, and sets up event capture.
                    </p>

                    <div className="flex flex-wrap gap-1.5">
                        <span className="text-xs text-muted">Supports:</span>
                        {WIZARD_FRAMEWORKS.map((fw) => (
                            <span
                                key={fw}
                                className="text-xs text-muted bg-bg-light border border-border rounded px-1.5 py-0.5"
                            >
                                {fw}
                            </span>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}
