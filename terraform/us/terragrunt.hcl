include "root" {
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

generate "provider.tf" {
  path      = "provider.tf"
  if_exists = "overwrite"
  contents  = file("provider.tf.tpl")
}

inputs = {
  posthog_api_key = get_env("POSTHOG_API_KEY")
}
