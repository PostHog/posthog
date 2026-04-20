provider "posthog" {
  api_key    = var.posthog_api_key
  host       = local.posthog_host
  project_id = var.posthog_project_id
}
