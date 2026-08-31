export interface WizardRunErrorDetails {
    title: string
    description: string
    resolution?: string
}

const WIZARD_RUN_ERROR_CATALOG: Record<string, WizardRunErrorDetails> = {
    PHW_CLI_NODE_VERSION: {
        title: 'The Node.js version is not supported',
        description: 'The Wizard cannot run with the Node.js version in this workspace.',
        resolution: 'Update Node.js to a supported version, then run the program again.',
    },
    PHW_CLI_BAD_ARGS: {
        title: 'The Wizard command is invalid',
        description: 'The command contains an unknown option or program name.',
    },
    PHW_CLI_FLAG_UNAVAILABLE: {
        title: 'A Wizard option is not available',
        description: 'The selected Wizard version does not support one of the command options.',
    },
    PHW_CLI_INTERACTIVE_REQUIRED: {
        title: 'This program needs an interactive terminal',
        description: 'The program cannot run unattended in the cloud.',
        resolution: 'Copy the local command from the Wizard Library and run it in your project folder.',
    },
    PHW_ARGS_MISSING_API_KEY: {
        title: 'The Wizard could not authenticate',
        description: 'The run did not receive a PostHog API key.',
    },
    PHW_ARGS_MISSING_INSTALL_DIR: {
        title: 'The project folder is missing',
        description: 'The run did not receive a project folder.',
    },
    PHW_ARGS_MISSING_EMAIL: {
        title: 'An email address is required',
        description: 'The selected signup flow needs an email address.',
    },
    PHW_ARGS_SIGNUP_PROVISION_FAILED: {
        title: 'PostHog account setup failed',
        description: 'The Wizard could not finish account setup.',
        resolution: 'Try the program again. If it still fails, contact PostHog support.',
    },
    PHW_AUTH_KEY_TYPE: {
        title: 'The API key type is not supported',
        description: 'The Wizard received a key that cannot authenticate this program.',
        resolution: 'Sign in again with the required PostHog credentials, then retry the program.',
    },
    PHW_AUTH_MISSING_SCOPE: {
        title: 'The API key needs more access',
        description: 'The current key does not include a scope required by this program.',
        resolution: 'Reconnect PostHog with the required access, then run the program again.',
    },
    PHW_AUTH_REGION_MISMATCH: {
        title: 'The PostHog region does not match',
        description: 'The credentials belong to a different PostHog region.',
        resolution: 'Connect credentials for this PostHog region, then run the program again.',
    },
    PHW_AUTH_INVALID_OR_EXPIRED: {
        title: 'The PostHog credentials are invalid or expired',
        description: 'The Wizard could not use the current credentials.',
        resolution: 'Sign in to PostHog again, then retry the program.',
    },
    PHW_AUTH_SETTINGS_CONFLICT: {
        title: 'Local settings override PostHog authentication',
        description: 'A Claude settings file replaces the credentials provided by the Wizard.',
        resolution: 'Remove the conflicting credential setting, then run the program again.',
    },
    PHW_AUTH_STORED_LOGIN_CONFLICT: {
        title: 'A stored Claude login overrides PostHog authentication',
        description: 'The agent used a stored login instead of the credentials provided by the Wizard.',
        resolution: 'Sign out of the stored Claude login, then run the program again.',
    },
    PHW_AUTH_PROJECT_FETCH_FAILED: {
        title: 'The Wizard could not load the PostHog project',
        description: 'PostHog project data was unavailable during the run.',
        resolution: 'Try the program again. If it still fails, contact PostHog support.',
    },
    PHW_ENV_LOCAL_SERVICES_DOWN: {
        title: 'Required local services are not running',
        description: 'The Wizard cannot reach a service needed for local development.',
        resolution: 'Start the required local services, then run the program again.',
    },
    PHW_ENV_SERVICE_OUTAGE: {
        title: 'A required service is unavailable',
        description: 'The Wizard cannot reach a service needed to complete this program.',
        resolution: 'Wait a few minutes, then run the program again.',
    },
    PHW_DETECT_BAD_DIRECTORY: {
        title: 'The project folder is not accessible',
        description: 'The selected folder is missing, unreadable, or not a directory.',
        resolution: 'Run the Wizard from a readable project folder.',
    },
    PHW_DETECT_NO_FRAMEWORK: {
        title: 'No supported framework was found',
        description: 'The Wizard could not detect a supported framework in this workspace.',
        resolution: 'Select the repository that contains your project root, then run the program again.',
    },
    PHW_DETECT_UNSUPPORTED_VERSION: {
        title: 'The framework version is not supported',
        description: 'The detected framework version is older than the Wizard supports.',
        resolution: 'Update the framework, then run the program again.',
    },
    PHW_DETECT_UNSUPPORTED_PLATFORM: {
        title: 'This project does not support the selected program',
        description: 'The Wizard has no compatible setup path for the detected platform.',
        resolution: 'Choose a program that supports this project, or follow the manual setup guide.',
    },
    PHW_DETECT_NO_POSTHOG_SDK: {
        title: 'No PostHog SDK was found',
        description: 'This program needs an existing PostHog SDK installation.',
        resolution: 'Run the PostHog integration program first, then run this program again.',
    },
    PHW_DETECT_NO_PROJECT_FILES: {
        title: 'No project files were found',
        description: 'The workspace does not contain files that this program can update.',
        resolution: 'Select a repository that contains your project, then run the program again.',
    },
    PHW_DETECT_NO_SOURCES: {
        title: 'No data warehouse sources were found',
        description: 'This program needs at least one connected data warehouse source.',
        resolution: 'Connect a data warehouse source in PostHog, then run the program again.',
    },
    PHW_SKILL_MENU_FETCH_FAILED: {
        title: 'The Wizard could not load its setup programs',
        description: 'The program catalog was unavailable during the run.',
        resolution: 'Wait a few minutes, then run the program again.',
    },
    PHW_SKILL_NOT_FOUND: {
        title: 'The selected setup program is unavailable',
        description: 'The Wizard could not find the selected program in its catalog.',
        resolution: 'Return to the Wizard Library and select an available program.',
    },
    PHW_SKILL_DOWNLOAD_FAILED: {
        title: 'The setup program could not be downloaded',
        description: 'The Wizard could not prepare the selected program.',
        resolution: 'Wait a few minutes, then run the program again.',
    },
    PHW_AGENT_ABORT: {
        title: 'The setup agent stopped the run',
        description: 'The agent found a condition that prevented it from continuing safely.',
        resolution: 'Review the project requirements, then run the program again.',
    },
    PHW_AGENT_MCP_MISSING: {
        title: 'The setup agent could not connect to PostHog',
        description: 'The PostHog tools required by the agent were unavailable.',
        resolution: 'Wait a few minutes, then run the program again.',
    },
    PHW_AGENT_RESOURCE_MISSING: {
        title: 'A required setup resource is unavailable',
        description: 'The agent could not load a resource needed by this program.',
        resolution: 'Wait a few minutes, then run the program again.',
    },
    PHW_AGENT_RATE_LIMIT: {
        title: 'The setup agent reached a rate limit',
        description: 'The AI service temporarily stopped accepting requests.',
        resolution: 'Wait a few minutes, then run the program again.',
    },
    PHW_AGENT_API_ERROR: {
        title: 'The setup agent lost access to a required service',
        description: 'An API request failed while the program was running.',
        resolution: 'Wait a few minutes, then run the program again.',
    },
    PHW_AGENT_YARA_VIOLATION: {
        title: 'A security check stopped the run',
        description: 'The agent produced content that did not pass the security check.',
    },
    PHW_AGENT_NO_PROGRESS: {
        title: 'The setup agent made no changes',
        description: 'The agent stopped before it could inspect or update the project.',
        resolution: 'Run the program again. If it still fails, use the local command.',
    },
    PHW_AGENT_INCOMPLETE_TASKS: {
        title: 'The setup agent did not finish every task',
        description: 'The run ended with required setup work still open.',
        resolution: 'Run the program again to finish the remaining work.',
    },
    PHW_AGENT_ORCHESTRATOR_SKILL_VARIANT_MISSING: {
        title: 'A required setup program is unavailable',
        description: 'The agent could not download a program for one of its planned tasks.',
        resolution: 'Wait a few minutes, then run the program again.',
    },
    PHW_AGENT_ORCHESTRATOR_TASKS_FAILED: {
        title: 'One or more setup tasks failed',
        description: 'The agent could not complete all required tasks.',
        resolution: 'Run the program again. If it still fails, review the project requirements.',
    },
    PHW_AGENT_ORCHESTRATOR_SINK_INVARIANT: {
        title: 'The setup plan is invalid',
        description: 'The agent could not create a safe plan for the selected program.',
    },
    PHW_SETTINGS_UNFIXABLE_CONFLICT: {
        title: 'A local settings conflict cannot be fixed automatically',
        description: 'A managed or read-only Claude setting conflicts with the Wizard.',
        resolution: 'Update the conflicting setting, then run the program again.',
    },
    PHW_INTERNAL_UNHANDLED: {
        title: 'The Wizard encountered an unexpected error',
        description: 'The program stopped because of an error that the Wizard did not recognize.',
        resolution: 'Run the program again. If it still fails, contact PostHog support.',
    },
}

export function wizardRunErrorDetails(errorCode: string | null, fallbackMessage: string | null): WizardRunErrorDetails {
    if (errorCode && WIZARD_RUN_ERROR_CATALOG[errorCode]) {
        return WIZARD_RUN_ERROR_CATALOG[errorCode]
    }

    const description = fallbackMessage || 'The Wizard run failed before it could finish.'

    return {
        title: description,
        description,
    }
}
