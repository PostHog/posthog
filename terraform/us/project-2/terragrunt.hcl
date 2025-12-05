generate "variables_project.tf" {
  path      = "variables_project.tf"
  if_exists = "overwrite"
  contents  = file("variables_project.tf.tpl")
}
