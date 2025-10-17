use std::sync::Arc;

use anyhow::{Context, Error};
use chrono::Duration;
use common_types::{InternallyCapturedEvent, RawEvent};
use rayon::iter::IntoParallelIterator;
use rayon::prelude::*;
use serde::{de::DeserializeOwned, Deserialize, Serialize};

use crate::{context::AppContext, job::model::JobModel};

use super::{
    content::{
        amplitude::AmplitudeEvent, captured::captured_parse_fn, mixpanel::MixpanelEvent,
        ContentType, TransformContext,
    },
    Parsed,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum FormatConfig {
    JsonLines {
        skip_blanks: bool,
        content: ContentType,
    },
}

pub type ParserFn =
    Box<dyn Fn(Vec<u8>) -> Result<Parsed<Vec<InternallyCapturedEvent>>, Error> + Send + Sync>;

impl FormatConfig {
    pub async fn get_parser(
        &self,
        model: &JobModel,
        context: Arc<AppContext>,
    ) -> Result<ParserFn, Error> {
        // Only support json-lines for now
        let Self::JsonLines {
            skip_blanks,
            content,
        } = self;

        let transform_context = TransformContext {
            team_id: model.team_id,
            token: context.get_token_for_team_id(model.team_id).await?,
            job_id: model.id,
            identify_cache: context.identify_cache.clone(),
            group_cache: context.group_cache.clone(),
            import_events: model.import_config.import_events,
            generate_identify_events: model.import_config.generate_identify_events,
            generate_group_identify_events: model.import_config.generate_group_identify_events,
        };

        match content {
            ContentType::Mixpanel(config) => {
                let format_parse = json_nd(*skip_blanks);

                let event_transform = MixpanelEvent::parse_fn(
                    transform_context,
                    config.skip_no_distinct_id,
                    config
                        .timestamp_offset_seconds
                        .map(Duration::seconds)
                        .unwrap_or_default(),
                    skip_geoip(),
                );

                let parser = move |data| {
                    let parsed: Parsed<Vec<MixpanelEvent>> = format_parse(data)?;
                    let consumed = parsed.consumed;
                    let result: Result<_, Error> = parsed
                        .data
                        .into_par_iter()
                        .map(&event_transform)
                        .filter_map(|x| x.transpose())
                        .collect();

                    Ok(Parsed {
                        data: result?,
                        consumed,
                    })
                };

                Ok(Box::new(parser))
            }
            ContentType::Amplitude => {
                let format_parse = json_nd(*skip_blanks);
                let event_transform = AmplitudeEvent::parse_fn(transform_context, skip_geoip());
                let parser = move |data| {
                    let parsed: Parsed<Vec<AmplitudeEvent>> = format_parse(data)?;
                    let consumed = parsed.consumed;
                    let result: Vec<_> = parsed
                        .data
                        .into_par_iter()
                        .map(&event_transform)
                        .filter_map(|x| x.ok())
                        .flatten()
                        .collect();

                    Ok(Parsed {
                        data: result,
                        consumed,
                    })
                };

                Ok(Box::new(parser))
            }
            ContentType::Captured => {
                let format_parse = json_nd(*skip_blanks);
                let event_transform = captured_parse_fn(transform_context, skip_geoip());
                let parser = move |data| {
                    let parsed: Parsed<Vec<RawEvent>> = format_parse(data)?;
                    let consumed = parsed.consumed;
                    let result: Result<_, Error> = parsed
                        .data
                        .into_par_iter()
                        .map(&event_transform)
                        .filter_map(|x| x.transpose())
                        .collect();

                    Ok(Parsed {
                        data: result?,
                        consumed,
                    })
                };

                Ok(Box::new(parser))
            }
        }
    }
}

const NEWLINE_DELIM: u8 = b'\n';

pub fn newline_delim<T: Send>(
    skip_blank_lines: bool,
    inner: impl Fn(&str) -> Result<T, Error> + Sync,
) -> impl Fn(Vec<u8>) -> Result<Parsed<Vec<T>>, Error> {
    move |data: Vec<u8>| {
        let mut cursor = 0;
        let mut last_consumed_byte = 0;

        let mut lines = Vec::new();

        // Note that we can't parse the entire buffer as a string and then iterate over the lines/characters here,
        // because it is possible for us to have split the file on a utf8 character boundary, meaning the last line in the
        // input will end in an invalid utf8 byte sequence. Instead, we iterate over the bytes directly, and only convert
        // them to utf8 when we've got a complete line.
        while cursor < data.len() {
            // The cursor != 0 bit here is because the "this might be the end of the file" handling below this can sometimes
            // cause the next chunk to start exactly on a newline. This does run the risk of accidentally skipping a blank line,
            // but we generally don't consider newlines important anyway (skip_blank_lines is generally only set to false to ensure
            // the presence of one in the input will cause the inner function to return an error, not because they're semantically
            // relevant)
            if data[cursor] == NEWLINE_DELIM && cursor != 0 {
                let line = std::str::from_utf8(&data[last_consumed_byte..cursor])
                    .context("Failed to parse line as utf8")?;
                if !skip_blank_lines || !line.trim().is_empty() {
                    lines.push((cursor, line.trim()));
                }
                last_consumed_byte = cursor;
            }

            cursor += 1;
        }

        // Sometimes we've split the file on a utf8 character boundary, and the last line is incomplete not just as
        // a line that can be fed to the inner parser, but as a utf8 string in general. If that's the case, just set
        // the remainder to be empty, and we can handle it in the next chunk.
        let remainder = std::str::from_utf8(&data[last_consumed_byte..]).unwrap_or("");
        let remainder = inner(remainder);

        let mut output = Vec::with_capacity(lines.len());
        let intermediate: Vec<_> = lines
            .into_par_iter()
            .map(|(end_byte_idx, line)| (end_byte_idx, inner(line)))
            .collect();

        drop(data);

        let mut last_validly_consumed_byte = 0;
        for (byte_idx, res) in intermediate.into_iter() {
            match res {
                Ok(parsed) => {
                    output.push(parsed);
                    last_validly_consumed_byte = byte_idx;
                }
                Err(e) => {
                    return Err(e.context(format!(
                        "Starting at byte {last_validly_consumed_byte} of current chunk"
                    )));
                }
            }
        }

        // If we managed to parse the last line, add it too, but if we didn't, assume it's due to this chunk being partway through the file,
        // and carry on.
        if let Ok(parsed) = remainder {
            output.push(parsed);
            // -1 because at this point the cursor is pointing at the end of the data,
            // and we want to point at the last byte we actually consumed
            last_validly_consumed_byte = cursor - 1;
        }

        let parsed = Parsed {
            data: output,
            consumed: last_validly_consumed_byte + 1,
        };

        Ok(parsed)
    }
}

pub fn json_nd<T>(skip_blank_lines: bool) -> impl Fn(Vec<u8>) -> Result<Parsed<Vec<T>>, Error>
where
    T: DeserializeOwned + Send,
{
    newline_delim(skip_blank_lines, |line| {
        let parsed = serde_json::from_str(line).context("Failed to json parse line")?;
        Ok(parsed)
    })
}

pub fn skip_geoip() -> impl Fn(RawEvent) -> Result<Option<RawEvent>, Error> {
    move |mut event| {
        event
            .properties
            .insert("$geoip_disable".to_string(), serde_json::Value::Bool(true));

        Ok(Some(event))
    }
}

#[cfg(test)]
mod tests {
    use crate::source::{folder::FolderSource, DataSource};

    use super::*;
    use serde::Deserialize;
    use std::fs;
    use tempfile::TempDir;

    #[derive(Deserialize, Debug, PartialEq)]
    struct TestData {
        id: i32,
        name: String,
    }

    async fn setup_test_files() -> (TempDir, FolderSource) {
        let temp_dir = TempDir::new().unwrap();
        fs::write(
            temp_dir.path().join("data.jsonl"),
            r#"{"id": 1, "name": "test1"}
{"id": 2, "name": "test2"}
{"id": 3, "name": "test3"}"#,
        )
        .unwrap();

        fs::write(
            temp_dir.path().join("blank_lines.jsonl"),
            r#"{"id": 1, "name": "test1"}

{"id": 2, "name": "test2"}
"#,
        )
        .unwrap();

        let source = FolderSource::new(temp_dir.path().to_str().unwrap().to_string())
            .await
            .unwrap();

        (temp_dir, source)
    }

    #[tokio::test]
    async fn test_json_nd_parsing() {
        let (_temp_dir, source) = setup_test_files().await;
        let chunk = source.get_chunk("data.jsonl", 0, 100).await.unwrap();
        let chunk_len = chunk.len();
        let parsed = json_nd::<TestData>(false)(chunk).unwrap();

        assert_eq!(parsed.data.len(), 3);
        assert_eq!(
            parsed.data[0],
            TestData {
                id: 1,
                name: "test1".to_string()
            }
        );
        assert_eq!(parsed.consumed, chunk_len);
    }

    #[tokio::test]
    async fn test_json_nd_with_blank_lines() {
        let (_temp_dir, source) = setup_test_files().await;
        let data = source.get_chunk("blank_lines.jsonl", 0, 100).await.unwrap();

        let parsed_with_blanks = json_nd::<TestData>(true)(data.clone()).unwrap();
        assert_eq!(parsed_with_blanks.data.len(), 2);

        // IF we're not skipping blank lines, an empty line will cause json parsing
        // to fail, and we should get an error
        let should_be_error = json_nd::<TestData>(false)(data);
        assert!(should_be_error.is_err());
    }

    #[tokio::test]
    async fn test_partial_line() {
        let (_temp_dir, source) = setup_test_files().await;
        let data = source.get_chunk("data.jsonl", 0, 30).await.unwrap();
        let parsed = json_nd::<TestData>(false)(data).unwrap();

        assert_eq!(parsed.data.len(), 1);
        // 26 "data" characters, plus the newline
        assert_eq!(parsed.consumed, 27);
    }
}
