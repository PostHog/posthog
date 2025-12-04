include "region" {
  path = find_in_parent_folders()
}

generate "locals_project.tf" {
  path      = "locals_project.tf"
  if_exists = "overwrite"
  contents  = file("locals_project.tf.tpl")
}

generate "variables.tf" {
  path      = "variables.tf"
  if_exists = "overwrite"
  contents  = file("variables.tf.tpl")
}
