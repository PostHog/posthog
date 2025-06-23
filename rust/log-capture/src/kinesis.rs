use apache_avro::{
    types::Record, types::Value, Codec, Days, Decimal, Duration, Error, Millis, Months, Reader,
    Schema, Writer,
};
use aws_config;
use aws_sdk_kinesis;
use aws_sdk_kinesis::types::PutRecordsRequestEntry;
use serde_json;
use uuid::Uuid;

use crate::log_record::IcebergLogRow;

const MAX_RECORD_SIZE: usize = 1_000_000;
const MAX_BATCH_SIZE: usize = 5_000_000;

#[derive(Clone)]
pub struct KinesisWriter {
    client: aws_sdk_kinesis::Client,
}

impl KinesisWriter {
    pub async fn new() -> Self {
        let config = aws_config::load_from_env().await;
        let client = aws_sdk_kinesis::Client::new(&config);
        KinesisWriter { client }
    }

    pub async fn write(&self, rows: Vec<IcebergLogRow>) -> Result<(), anyhow::Error> {
        let mut request = self.client.put_records().stream_name("iceberg-logs-stream");
        let schema = Schema::parse_str(AVRO_SCHEMA)?;

        let mut writer = Writer::with_codec(&schema, Vec::new(), Codec::Deflate);

        let mut total_size = 0;
        for row in rows.iter() {
            writer.append_ser(row)?;
        }
        let entry = PutRecordsRequestEntry::builder()
            .data(writer.into_inner()?.into())
            .partition_key(Uuid::new_v4().to_string())
            .build()?;
        request = request.records(entry);
        request.send().await?;
        Ok(())
    }
}
