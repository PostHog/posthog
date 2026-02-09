terraform {
  required_version = ">= 1.13.0"
  required_providers {
    posthog = {
      source  = "PostHog/posthog"
      version = "1.0.2"
    }
  }
}
