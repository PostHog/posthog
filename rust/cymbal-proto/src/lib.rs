pub mod cymbal {
    pub mod process {
        pub mod v1 {
            tonic::include_proto!("cymbal.process.v1");
        }
    }

    pub mod resolution {
        pub mod v1 {
            tonic::include_proto!("cymbal.resolution.v1");
        }
    }
}
