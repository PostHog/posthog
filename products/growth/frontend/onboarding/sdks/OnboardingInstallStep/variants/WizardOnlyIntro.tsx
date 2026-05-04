import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

/**
 * Intro for the wizard-only install variant.
 *
 * Experiment: onboarding-wizard-installation-improved-copy (#team-growth)
 *   control — original one-line tagline
 *   test    — expanded copy that concretely enumerates what the wizard does,
 *             adds short "how it works" instructions (run from project root,
 *             follow prompts), and surfaces that PostHog covers LLM inference
 *             (no user API key required)
 *
 * Hypothesis: users are more likely to try the wizard when they understand
 * what it does, where to run it, and that it's free to run.
 *
 * Flag lookup is encapsulated here so WizardOnlyVariant stays agnostic of
 * the experiment. When the experiment concludes, the winning variant
 * replaces the dispatcher and this file collapses to a single component.
 */
export function WizardOnlyIntro(): JSX.Element {
    const isImprovedCopy = useFeatureFlag('ONBOARDING_WIZARD_INSTALLATION_IMPROVED_COPY', 'test')
    return isImprovedCopy ? <ImprovedIntro /> : <ControlIntro />
}

function ControlIntro(): JSX.Element {
    return (
        <div className="text-center max-w-lg mx-auto">
            <h2 className="text-2xl font-bold mb-2">Install PostHog with one command</h2>
            <p className="text-muted">
                Our AI wizard detects your framework, installs the right SDK, and configures event capture
                automatically.
            </p>
        </div>
    )
}

function ImprovedIntro(): JSX.Element {
    return (
        <div className="text-center max-w-xl mx-auto space-y-3">
            <h2 className="text-2xl font-bold">Let the AI wizard install PostHog for you</h2>
            <p className="text-muted">
                Run this command from your project&apos;s root directory. The wizard detects your framework, installs
                the right SDK, configures your environment variables, and wires up event capture automatically.
            </p>
            <p className="text-muted text-xs">LLM inference is on us — no API key needed.</p>
        </div>
    )
}
