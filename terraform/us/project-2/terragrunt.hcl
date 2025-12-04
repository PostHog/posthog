include "region" {
  path = find_in_parent_folders()
}

generate "locals.tf" {
  path      = "locals.tf"
  if_exists = "overwrite"
  contents  = file("locals.tf.tpl")
}

generate "variables.tf" {
  path      = "variables.tf"
  if_exists = "overwrite"
  contents  = file("variables.tf.tpl")
}
