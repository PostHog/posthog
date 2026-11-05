# Local Wizard Development

Set this variable before you start PostHog:

```text
LOCAL_WIZARD_ROOT=/Users/fcgomes/posthog-dev/wizard
```

This option works only when Django debug mode is active.

For each cloud run, the Temporal worker copies the local Wizard source into the sandbox. The sandbox installs the dependencies and builds the Wizard before execution.

Restart the PostHog backend and Temporal worker after you change the variable. You do not need to restart them after you change Wizard source files.

## Gateway token

A local PostHog does not have the settings to mint Wizard gateway tokens.
To send the model calls of a local cloud run to the production AI gateway, put the dev gateway service key (`phs_...`, in 1Password) in a file and set this variable:

```text
LOCAL_WIZARD_GATEWAY_TOKEN_FILE=~/.config/posthog/wizard-gateway-token
```

Restrict the file permissions with `chmod 600`.
This option works only with `LOCAL_WIZARD_ROOT` and Django debug mode.
The Temporal worker copies the key into the sandbox, and the Wizard uses the key in place of a minted token.
The agent in the sandbox can read the key, so use this option only with test repositories.
Restart the Temporal worker after you change the variable.
