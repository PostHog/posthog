terraform {
  source = "."

  extra_arguments "init" {
    commands = ["init"]
    arguments = ["-input=false"]
  }
}

generate "providers_root.tf" {
  path      = "providers_root.tf"
  if_exists = "overwrite"
  contents  = file("providers_root.tf.tpl")
}

remote_state {
  backend = "s3"
  generate = {
    path      = "backends.tf"
    if_exists = "overwrite"
  }
  config = {
    bucket         = get_env("POSTHOG_PROVIDER_TF_STATE_BUCKET")
    key            = "posthog-provider/${path_relative_to_include()}/terraform.tfstate"
    region         = get_env("POSTHOG_PROVIDER_TF_STATE_REGION")
    use_lockfile   = true
    encrypt        = true
  }
}
