# Team-level configuration for team-analytics-platform
# This file is NOT directly runnable - it provides shared config for child modules.
# Child modules use read_terragrunt_config() to import these settings.

# Generate shared team variables in each child module
generate "variables_team" {
  path      = "variables_team.tf"
  if_exists = "overwrite"
  contents  = file("${get_terragrunt_dir()}/variables_team.tf.tpl")
}

# Team-level inputs shared across all child modules
# Secret values should be stored as env vars in the Github project.
inputs = {
  analytics_platform_slack_channel_id          = "C09S5802LMU"
  analytics_platform_slack_workspace_id        = 54567
  analytics_platform_alert_subscribed_user_ids = [339134]
}
