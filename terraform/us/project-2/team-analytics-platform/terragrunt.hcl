include "root" {
  path   = find_in_parent_folders("root.hcl")
  expose = true
}

include "region" {
  path   = "../../terragrunt.hcl"
  expose = true
}

include "project" {
  path   = "../terragrunt.hcl"
  expose = true
}

# Generate shared team variables in each child module
generate "variables_team" {
  path      = "variables_team.tf"
  if_exists = "overwrite"
  contents  = file("variables_team.tf.tpl")
}

# Team-level inputs shared across all child modules
# These values are passed down to child modules via terragrunt's input inheritance.
# Secret values should be stored as env vars in the Github project.
inputs = {
  analytics_platform_slack_channel_id         = "C09S5802LMU"
  analytics_platform_slack_workspace_id       = 54567
  analytics_platform_alert_subscribed_user_ids = [339134]
}
