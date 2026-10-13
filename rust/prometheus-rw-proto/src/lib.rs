pub mod prometheus {
    pub mod v1 {
        // No gRPC service in this proto, so the generated file is pure prost
        // message types with no tonic dependency — include it directly rather
        // than via tonic::include_proto!.
        include!(concat!(env!("OUT_DIR"), "/prometheus.v1.rs"));
    }
}
