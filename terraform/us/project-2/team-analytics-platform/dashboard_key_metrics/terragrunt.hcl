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

include "team" {
  path   = "../terragrunt.hcl"
  expose = true
}
