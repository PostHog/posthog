use crate::{frames::RawFrame, types::Exception};

#[derive(Clone)]
pub struct ExceptionResolver;

impl ExceptionResolver {
    pub fn is_java_exception(exc: &Exception) -> bool {
        let first_frame = exc.stack.as_ref().and_then(|s| s.get_raw_frames().first());
        // Implementation for checking if the exception is a Java exception
        if let Some(RawFrame::Java(_)) = first_frame {
            if exc.module.is_some() {
                return true;
            }
        }
        false
    }

    pub fn is_dart_exception(exc: &Exception) -> bool {
        // Checking if the exception is a Dart exception
        exc.exception_type.starts_with("minified:")
    }
}

#[cfg(test)]
mod test {
    use std::sync::Arc;

    use chrono::Utc;
    use mockall::predicate;
    use posthog_symbol_data::{write_symbol_data, JvmBundle};
    use sqlx::PgPool;
    use uuid::Uuid;

    use crate::{
        frames::RawFrame,
        langs::{java::RawJavaFrame, CommonFrameMetadata},
        modes::processing::config::ProcessingConfig,
        symbolication::symbol::{local::LocalSymbolResolver, SymbolResolver},
        symbolication::symbol_store::{
            apple::AppleProvider, chunk_id::ChunkIdFetcher, hermesmap::HermesMapProvider,
            native::NativeProvider, proguard::ProguardProvider, saving::SymbolSetRecord,
            sourcemap::SourcemapProvider, Catalog, MockS3Client,
        },
        types::{Exception, Stacktrace},
    };

    const PROGUARD_MAP: &str =
        include_str!("../../../../../tests/static/proguard/mapping_example.txt");

    async fn resolver_with_symbol_set(
        db: PgPool,
        team_id: i32,
        set_ref: &str,
        data: Vec<u8>,
    ) -> LocalSymbolResolver {
        let mut config = ProcessingConfig::init_with_defaults().unwrap();
        config.resolver.object_storage_bucket = "test-bucket".to_string();

        let mut record = SymbolSetRecord {
            id: Uuid::now_v7(),
            team_id,
            set_ref: set_ref.to_string(),
            storage_ptr: Some(set_ref.to_string()),
            failure_reason: None,
            created_at: Utc::now(),
            content_hash: Some("fake-hash".to_string()),
            last_used: Some(Utc::now()),
        };

        record.save(&db).await.unwrap();

        let mut client = MockS3Client::default();

        client
            .expect_get()
            .with(
                predicate::eq(config.resolver.object_storage_bucket.clone()),
                predicate::eq(set_ref.to_string()), // We set the set ref as the storage ptr above, in production it will be a different value with a prefix
            )
            .returning(move |_, _| Ok(Some(bytes::Bytes::from(data.clone()))));

        let client = Arc::new(client);
        let bucket = config.resolver.object_storage_bucket.clone();

        let hmp = ChunkIdFetcher::new(
            HermesMapProvider::new(&config.resolver),
            client.clone(),
            db.clone(),
            bucket.clone(),
        );
        let smp = ChunkIdFetcher::new(
            SourcemapProvider::new(&config.resolver),
            client.clone(),
            db.clone(),
            bucket.clone(),
        );
        let pgp = ChunkIdFetcher::new(
            ProguardProvider::new(&config.resolver),
            client.clone(),
            db.clone(),
            bucket.clone(),
        );
        let apple = ChunkIdFetcher::new(
            AppleProvider::new(&config.resolver),
            client.clone(),
            db.clone(),
            bucket.clone(),
        );
        let native = ChunkIdFetcher::new(
            NativeProvider::new(&config.resolver),
            client.clone(),
            db.clone(),
            bucket,
        );

        let c = Catalog::new(smp, hmp, pgp, apple, native);
        LocalSymbolResolver::new(&config.resolver, Arc::new(c), db)
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_proguard_resolution(db: PgPool) {
        let team_id = 1;
        let map_id = "com.posthog.android.sample@3.0+3".to_string();
        let resolver =
            resolver_with_symbol_set(db, team_id, &map_id, get_symbol_data_bytes()).await;

        let frame = RawJavaFrame {
            module: "a1.d".to_string(),
            filename: Some("SourceFile".to_string()),
            function: "onClick".to_string(),
            lineno: Some(14),
            map_id: Some(map_id),
            context_line: None,
            pre_context: Vec::new(),
            post_context: Vec::new(),
            method_synthetic: false,
            meta: CommonFrameMetadata::default(),
        };

        let exception = Exception {
            exception_type: "c".to_string(),
            module: Some("a1".to_string()),
            exception_message: "Exception message".to_string(),
            exception_id: None,
            mechanism: None,
            thread_id: None,
            stack: Some(Stacktrace::Raw {
                frames: vec![RawFrame::Java(frame)],
            }),
        };

        let result = resolver
            .resolve_java_exception(team_id, exception)
            .await
            .unwrap();

        assert_eq!(
            result.module,
            Some("com.posthog.android.sample".to_string()),
        );

        assert_eq!(result.exception_type, "MyCustomException3".to_string(),);
    }

    #[sqlx::test(migrations = "./tests/test_migrations")]
    async fn test_jvm_sources_resolution(db: PgPool) {
        let team_id = 1;
        let map_id = "6f1c3c2e-6f61-5c1b-9a52-3b6e4f0d7a10".to_string();
        let source = "package com.acme.billing;\n\nclass InvoiceService {\n    void charge() {\n        throw new IllegalStateException(\"boom\");\n    }\n}\n";
        let data = write_symbol_data(JvmBundle {
            mapping: None,
            sources: [(
                "com/acme/billing/InvoiceService.java".to_string(),
                source.to_string(),
            )]
            .into(),
        })
        .unwrap();
        let resolver = resolver_with_symbol_set(db, team_id, &map_id, data).await;

        let frame = RawJavaFrame {
            module: "com.acme.billing.InvoiceService".to_string(),
            filename: Some("InvoiceService.java".to_string()),
            function: "charge".to_string(),
            lineno: Some(5),
            map_id: Some(map_id),
            context_line: None,
            pre_context: Vec::new(),
            post_context: Vec::new(),
            method_synthetic: false,
            meta: CommonFrameMetadata::default(),
        };
        let frames = resolver
            .resolve_raw_frame(team_id, &RawFrame::Java(frame), &[])
            .await
            .unwrap();
        assert_eq!(frames.len(), 1);
        let resolved = &frames[0];
        assert!(resolved.resolved);
        assert_eq!(resolved.resolve_failure, None);
        assert_eq!(resolved.resolved_name, None);
        let context = resolved.context.as_ref().expect("source context");
        assert_eq!(context.line.number, 5);
        assert_eq!(
            context.line.line,
            "        throw new IllegalStateException(\"boom\");"
        );
        assert_eq!(context.before.len(), 4);
        assert_eq!(context.after.len(), 2);
    }

    fn get_symbol_data_bytes() -> Vec<u8> {
        write_symbol_data(posthog_symbol_data::ProguardMapping {
            content: PROGUARD_MAP.to_string(),
        })
        .unwrap()
    }
}
