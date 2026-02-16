pub mod personhog {
    pub mod types {
        pub mod v1 {
            tonic::include_proto!("personhog.types.v1");
        }
    }
    pub mod replica {
        pub mod v1 {
            tonic::include_proto!("personhog.replica.v1");
        }
    }
    pub mod service {
        pub mod v1 {
            tonic::include_proto!("personhog.service.v1");
        }
    }
}
