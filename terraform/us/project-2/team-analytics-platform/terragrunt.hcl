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
