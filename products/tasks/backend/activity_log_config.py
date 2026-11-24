sandbox_custom_image_machine_fields = [
    "status",
    "version",
    "modal_image_name",
    "base_image_reference",
    "base_image_refresh_reference",
    "scan_result",
    "error",
    "build_log",
    "builder_task",
]


FIELD_EXCLUSIONS = {
    "SandboxCustomImage": sandbox_custom_image_machine_fields,
}


FIELD_WITH_MASKED_CONTENTS = {
    "SandboxEnvironment": ["environment_variables"],
    "SandboxCustomImage": ["spec"],
}


SIGNAL_EXCLUSIONS = {
    "SandboxCustomImage": [*sandbox_custom_image_machine_fields, "updated_at"],
}
