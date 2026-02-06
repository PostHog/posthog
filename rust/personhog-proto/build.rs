fn main() -> Result<(), Box<dyn std::error::Error>> {
    let proto_root = "../../proto";

    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile_protos(
            &[
                // Shared types
                format!("{proto_root}/personhog/types/v1/common.proto"),
                format!("{proto_root}/personhog/types/v1/person.proto"),
                format!("{proto_root}/personhog/types/v1/group.proto"),
                format!("{proto_root}/personhog/types/v1/cohort.proto"),
                format!("{proto_root}/personhog/types/v1/feature_flag.proto"),
                // Services
                format!("{proto_root}/personhog/replica/v1/replica.proto"),
                format!("{proto_root}/personhog/service/v1/service.proto"),
            ],
            &[proto_root],
        )?;
    Ok(())
}
