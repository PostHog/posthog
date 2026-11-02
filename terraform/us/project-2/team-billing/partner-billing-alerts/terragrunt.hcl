include "root" {
  path   = find_in_parent_folders("root.hcl")
  expose = true
}

include "region" {
  path   = "../../../terragrunt.hcl"
  expose = true
}

include "project" {
  path   = "../../terragrunt.hcl"
  expose = true
}

# Read team-level config for shared inputs and generate blocks
locals {
  team_config = read_terragrunt_config("${get_terragrunt_dir()}/../terragrunt.hcl")
}

# Generate team variables from parent config
generate "variables_team" {
  path      = "variables_team.tf"
  if_exists = "overwrite"
  contents  = file("${get_terragrunt_dir()}/../variables_team.tf.tpl")
}

# Merge team-level inputs. Partner billing alerts post to the channel without mentioning anyone.
inputs = merge(local.team_config.inputs, {
  billing_alert_mention_slack_user_ids = []
})
