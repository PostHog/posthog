# Local Wizard Development

Set this variable before you start PostHog:

```text
LOCAL_WIZARD_ROOT=/Users/fcgomes/posthog-dev/wizard
```

This option works only when Django debug mode is active.

For each cloud run, the Temporal worker copies the local Wizard source into the sandbox. The sandbox installs the dependencies and builds the Wizard before execution.

Restart the PostHog backend and Temporal worker after you change the variable. You do not need to restart them after you change Wizard source files.
