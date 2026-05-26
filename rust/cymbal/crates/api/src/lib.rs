//! Wire API definitions for Cymbal ingestion and internal stage services.

pub mod cymbal {
    pub mod v1 {
        tonic::include_proto!("cymbal.v1");
    }
}

#[cfg(test)]
mod tests {
    use prost::Message;

    use crate::cymbal::v1::{StageBatchResult, StageLoad};

    #[test]
    fn stage_batch_result_round_trips_load_signal() {
        let result = StageBatchResult {
            results: Vec::new(),
            errors: Vec::new(),
            load: Some(StageLoad {
                current_in_flight_stage_batches: 3,
                max_in_flight_stage_batches: 8,
                overloaded: false,
                current_in_flight_items: 7,
                max_in_flight_items: 64,
                draining: false,
                served_stage_ids: vec!["resolution:v1".to_string()],
            }),
        };
        let mut encoded = Vec::new();

        result.encode(&mut encoded).unwrap();
        let decoded = StageBatchResult::decode(encoded.as_slice()).unwrap();

        assert_eq!(decoded.load, result.load);
    }

    #[test]
    fn stage_batch_result_accepts_missing_optional_load() {
        let result_without_load = StageBatchResult {
            results: Vec::new(),
            errors: Vec::new(),
            load: None,
        };
        let mut encoded = Vec::new();

        result_without_load.encode(&mut encoded).unwrap();
        let decoded = StageBatchResult::decode(encoded.as_slice()).unwrap();

        assert_eq!(decoded.load, None);
    }
}
