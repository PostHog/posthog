# Team-level configuration for team-billing
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
  billing_slack_channel_id             = "C039XEY25ML" # #alerts-billing
  billing_slack_workspace_id           = 173069
  billing_alert_mention_slack_user_ids = ["U0BLTRYPJ3D"]
}
