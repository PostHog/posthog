fn main() -> Result<(), Box<dyn std::error::Error>> {
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile_protos(
            &[
                // Shared types
                "proto/personhog/types/v1/common.proto",
                "proto/personhog/types/v1/person.proto",
                "proto/personhog/types/v1/group.proto",
                "proto/personhog/types/v1/cohort.proto",
                "proto/personhog/types/v1/feature_flag.proto",
                // Services
                // Note: service/v1/service.proto is a placeholder for the router service (not yet implemented)
                "proto/personhog/replica/v1/replica.proto",
            ],
            &["proto/"],
        )?;
    Ok(())
}
