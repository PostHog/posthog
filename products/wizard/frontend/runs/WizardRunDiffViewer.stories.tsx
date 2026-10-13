import type { Meta, StoryObj } from '@storybook/react'

import { WizardRunDiffViewer } from './WizardRunDiffViewer'

const diff = `diff --git a/src/analytics.ts b/src/analytics.ts
index 8dc2f8a..c825f2d 100644
--- a/src/analytics.ts
+++ b/src/analytics.ts
@@ -1,9 +1,15 @@
 import posthog from 'posthog-js'
 ${''}
 export function initializeAnalytics(): void {
-    posthog.init('phc_example')
+    posthog.init('phc_example', {
+        api_host: 'https://us.i.posthog.com',
+        defaults: '2025-05-24',
+    })
 }
 ${''}
 export function trackSignup(plan: string): void {
-    posthog.capture('user signed up', { plan })
+    posthog.capture('user signed up', {
+        plan,
+        source: 'onboarding',
+    })
 }
diff --git a/src/identify.ts b/src/identify.ts
new file mode 100644
index 0000000..0ad1795
--- /dev/null
+++ b/src/identify.ts
@@ -0,0 +1,7 @@
+import posthog from 'posthog-js'
+
+export function identifyUser(id: string, email: string): void {
+    posthog.identify(id, {
+        email,
+    })
+}
`

const meta: Meta<typeof WizardRunDiffViewer> = {
    title: 'Products/Wizard/Wizard run diff viewer',
    component: WizardRunDiffViewer,
    parameters: { layout: 'fullscreen' },
    args: {
        diff,
        contentHash: 'sample-diff',
        sizeBytes: diff.length,
        pullRequestUrl: 'https://github.com/PostHog/posthog/pull/123',
    },
    decorators: [
        (Story) => (
            <div className="mx-auto w-full max-w-5xl p-6">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof WizardRunDiffViewer>

export const Default: Story = {}

export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-full max-w-lg p-4">
                <Story />
            </div>
        ),
    ],
}
