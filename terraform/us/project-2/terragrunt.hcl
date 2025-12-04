include "region" {
  path = find_in_parent_folders()
}

generate "locals_project.tf" {
  path      = "locals_project.tf"
  if_exists = "overwrite"
  contents  = file("locals_project.tf.tpl")
}

generate "variables_project.tf" {
  path      = "variables_project.tf"
  if_exists = "overwrite"
  contents  = file("variables_project.tf.tpl")
}
