terraform {
  required_version = local.terraform_version
  required_providers {
    posthog = {
      source  = "PostHog/posthog"
      version = local.posthog_provider_version
    }
  }
}
