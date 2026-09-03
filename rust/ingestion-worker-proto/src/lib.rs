pub mod ingestion {
    pub mod worker {
        pub mod v1 {
            tonic::include_proto!("ingestion.worker.v1");
        }
    }
}
