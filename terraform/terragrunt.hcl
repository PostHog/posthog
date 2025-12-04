generate "locals.tf" {
  path      = "locals.tf"
  if_exists = "overwrite"
  contents  = file("locals.tf.tpl")
}

generate "providers.tf" {
  path      = "providers.tf"
  if_exists = "overwrite"
  contents  = file("providers.tf.tpl")
}

remote_state {
  backend = "s3"
  generate = {
    path      = "backends.tf"
    if_exists = "overwrite"
  }
  config = {
    bucket         = get_env("TF_STATE_BUCKET")
    key            = "posthog-provider/${path_relative_to_include()}/terraform.tfstate"
    region         = get_env("TF_STATE_REGION")
    dynamodb_table = get_env("TF_STATE_LOCK_TABLE")
    encrypt        = true
  }
}
