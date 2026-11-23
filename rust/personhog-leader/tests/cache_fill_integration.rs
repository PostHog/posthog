mod common;

use std::sync::Arc;
use std::time::{Duration, Instant};

use common::{
    commit_writer_offset_at, create_mock_kafka, make_person, produce_garbage_to_partition,
    produce_person_to_partition, test_warming_config, warming_config_for, CHANGELOG_TOPIC,
};
use personhog_coordination::changelog::WarmSource;
use personhog_leader::cache::{
    CacheLookup, DirtyIndex, PartitionedCache, PersonCache, PersonCacheKey,
};
use personhog_leader::cache_fill::{
    fill_next_chunks, lookback_offset, run_fills, FillConfig, FillEnd, FillRequest, FillStats,
    Fills, PartitionFill,
};
use personhog_leader::warming::{warm_from_sources, WarmClientPools, WarmingConfig};
use personhog_proto::personhog::types::v1::Person;
use prost::Message as ProtoMessage;
use rdkafka::config::ClientConfig;
use rdkafka::consumer::{BaseConsumer, Consumer};
use rdkafka::mocking::MockCluster;
use rdkafka::producer::{DefaultProducerContext, FutureProducer, FutureRecord};
use rdkafka::{Message, Offset, TopicPartitionList};

fn version_of(cache: &PartitionedCache, partition: u32, person_id: i64) -> Option<i64> {
    let key = PersonCacheKey {
        team_id: 1,
        person_id,
    };
    match cache.get(partition, &key) {
        CacheLookup::Found(person) => Some(person.version),
        _ => None,
    }
}

fn serving(cache: &PartitionedCache) -> Arc<PersonCache> {
    cache.serving_cache(0).expect("partition 0 is serving")
}

const FILL: FillConfig = FillConfig {
    lookback: Duration::from_secs(3600),
    chunk_offsets: 2,
    target_fraction: 0.9,
    concurrency: 4,
};

async fn fill_to_end(
    cfg: &WarmingConfig,
    fill: &FillConfig,
    pools: &WarmClientPools,
    fills: &mut [PartitionFill],
) {
    let cluster = pools.on(None);
    while fills.iter().any(|filling| filling.stats().is_none()) {
        fill_next_chunks(cfg, fill, &cluster.warming, fills).await;
    }
}

async fn fill_source(
    cfg: &WarmingConfig,
    fill: &FillConfig,
    pools: &WarmClientPools,
    cache: &Arc<PersonCache>,
    source: &WarmSource,
    lower: i64,
    upper: i64,
) -> personhog_coordination::error::Result<FillStats> {
    let mut fills = [PartitionFill::new(
        source.partition,
        Arc::clone(cache),
        source.clone(),
        lower,
        upper,
    )];
    fill_to_end(cfg, fill, pools, &mut fills).await;
    let stats = fills[0].stats().expect("the fill has ended");
    if stats.end == FillEnd::Failed {
        return Err(personhog_coordination::error::Error::invalid_state(
            "the fill's read failed".to_string(),
        ));
    }
    Ok(stats)
}

/// Six applied records on partition 0, then a warm that finds nothing left to read.
async fn warmed_over_applied_history(
    cache: &PartitionedCache,
) -> (
    MockCluster<'static, DefaultProducerContext>,
    WarmingConfig,
    WarmClientPools,
    i64,
) {
    let (cluster, producer) = create_mock_kafka().await;
    let history = [
        Person {
            version: 1,
            ..make_person(1, 1)
        },
        Person {
            version: 1,
            ..make_person(1, 2)
        },
        Person {
            version: 1,
            ..make_person(1, 3)
        },
        Person {
            version: 2,
            ..make_person(1, 1)
        },
        Person {
            version: 2,
            is_deleted: true,
            ..make_person(1, 3)
        },
        Person {
            version: 3,
            ..make_person(1, 1)
        },
    ];
    for person in &history {
        produce_person_to_partition(&producer, 0, person).await;
    }
    commit_writer_offset_at(&cluster, "personhog-writer", 0, history.len() as i64);
    let dirty_index = DirtyIndex::new(1_000_000);
    let (cfg, pools) = warming_config_for("filler", &cluster);
    let sources = [WarmSource::live(CHANGELOG_TOPIC, None, 0)];
    let live_start = warm_from_sources(&cfg, &pools, cache, &dirty_index, 0, &sources, true)
        .await
        .expect("warming should succeed");
    assert!(dirty_index.is_empty());
    (cluster, cfg, pools, live_start)
}

#[tokio::test]
async fn the_lookback_offset_is_the_first_record_at_or_after_the_cutoff() {
    let topic = common::owned_broker_topic(1).await;
    let producer = common::create_kafka_producer_on(&topic.bootstrap_servers()).await;
    const HOUR_MS: i64 = 3_600_000;
    let now_ms = 1_790_000_000_000;
    for (person_id, age_hours) in [(1, 3), (2, 2), (3, 1)] {
        let person = make_person(1, person_id);
        let key = format!("1:{person_id}");
        let payload = person.encode_to_vec();
        let record = FutureRecord::to(&topic.topic)
            .key(&key)
            .partition(0)
            .timestamp(now_ms - age_hours * HOUR_MS)
            .payload(&payload);
        producer
            .send(record, Duration::from_secs(5))
            .await
            .expect("produce should succeed");
    }
    let cfg = test_warming_config("lookback", &topic.bootstrap_servers());
    let pools = WarmClientPools::new(&cfg.kafka, "lookback", &cfg.writer_consumer_group);
    let source = WarmSource::live(&topic.topic, None, 0);

    let cutoffs = [
        (now_ms - 4 * HOUR_MS, 0),
        (now_ms - 2 * HOUR_MS - HOUR_MS / 2, 1),
        (now_ms, 3),
    ];
    for (since_ms, expected) in cutoffs {
        let offset = lookback_offset(&cfg, &pools, &source, since_ms, 3)
            .await
            .expect("lookup should succeed");
        assert_eq!(offset, expected, "cutoff {since_ms}");
    }
}

#[tokio::test]
async fn a_fill_reads_each_record_once_when_markers_end_its_chunks() {
    use rdkafka::producer::Producer;

    let topic = common::owned_broker_topic(1).await;
    let producer: FutureProducer = ClientConfig::new()
        .set("bootstrap.servers", topic.bootstrap_servers())
        .set("transactional.id", format!("fill-{}", topic.topic))
        .create()
        .expect("transactional producer");
    producer
        .init_transactions(Duration::from_secs(10))
        .expect("init transactions");
    // One transaction per record, so every record is followed by a marker.
    for person_id in 1..=3 {
        producer.begin_transaction().expect("begin");
        let payload = make_person(1, person_id).encode_to_vec();
        let key = format!("1:{person_id}");
        producer
            .send(
                FutureRecord::to(&topic.topic)
                    .key(&key)
                    .partition(0)
                    .payload(&payload),
                Duration::from_secs(5),
            )
            .await
            .expect("produce should succeed");
        producer
            .commit_transaction(Duration::from_secs(10))
            .expect("commit");
    }
    let cfg = test_warming_config("markers", &topic.bootstrap_servers());
    let pools = WarmClientPools::new(&cfg.kafka, "markers", &cfg.writer_consumer_group);
    let cache = PartitionedCache::new(1 << 20);
    cache.begin_warm_partition(0);
    cache.track_puts(0);
    cache.publish_warmed_partition(0);
    let source = WarmSource::live(&topic.topic, None, 0);

    // The log end is taken only once every record is visible as committed, so the range
    // the fill is given holds all three whatever the broker still has to write.
    let reader: BaseConsumer = ClientConfig::new()
        .set("bootstrap.servers", topic.bootstrap_servers())
        .set("group.id", format!("fill-visible-{}", topic.topic))
        .set("isolation.level", "read_committed")
        .create()
        .expect("consumer");
    let mut from_start = TopicPartitionList::new();
    from_start
        .add_partition_offset(&topic.topic, 0, Offset::Beginning)
        .expect("partition offset");
    reader.assign(&from_start).expect("assign");
    let deadline = Instant::now() + Duration::from_secs(30);
    let mut visible = Vec::new();
    while visible.len() < 3 {
        assert!(
            Instant::now() < deadline,
            "committed records seen: {visible:?}"
        );
        if let Some(message) = reader.poll(Duration::from_millis(100)) {
            visible.push(message.expect("record").offset());
        }
    }
    let (_, end) = reader
        .fetch_watermarks(&topic.topic, 0, Duration::from_secs(5))
        .expect("watermarks");

    let stats = fill_source(&cfg, &FILL, &pools, &serving(&cache), &source, 0, end)
        .await
        .expect("fill should succeed");

    let filled: Vec<i64> = (1..=3)
        .filter(|person_id| version_of(&cache, 0, *person_id).is_some())
        .collect();
    assert_eq!(
        (stats.records, stats.inserted, filled),
        (3, 3, vec![1, 2, 3]),
        "log end {end}, records at offsets {visible:?}"
    );
}

#[tokio::test]
async fn a_fill_restores_the_newest_applied_record_of_each_live_person() {
    let cache = PartitionedCache::new(1 << 20);
    let (_cluster, cfg, pools, upper) = warmed_over_applied_history(&cache).await;
    assert_eq!(version_of(&cache, 0, 1), None);

    let source = WarmSource::live(CHANGELOG_TOPIC, None, 0);
    let stats = fill_source(&cfg, &FILL, &pools, &serving(&cache), &source, 0, upper)
        .await
        .expect("fill should succeed");

    assert_eq!((stats.end, stats.records), (FillEnd::Bound, 6));
    assert_eq!(version_of(&cache, 0, 1), Some(3));
    assert_eq!(version_of(&cache, 0, 2), Some(1));
    assert_eq!(version_of(&cache, 0, 3), None);
}

#[tokio::test]
async fn a_chunk_larger_than_the_caches_room_keeps_its_newest_persons_and_ends_the_fill() {
    let (cluster, producer) = create_mock_kafka().await;
    let large = |person_id: i64, version: i64, is_deleted: bool| Person {
        version,
        is_deleted,
        properties: serde_json::to_vec(&serde_json::json!({ "blob": "x".repeat(10_000) })).unwrap(),
        ..make_person(1, person_id)
    };
    // The newest chunk is the last four records. Person 1's is its oldest, and the two
    // deaths take room in the chunk but none in the cache, so room is left for an older chunk.
    let history = [
        make_person(1, 1),
        large(1, 2, false),
        large(2, 1, true),
        large(3, 1, true),
        large(4, 1, false),
    ];
    for person in &history {
        produce_person_to_partition(&producer, 0, person).await;
    }
    let (cfg, pools) = warming_config_for("overflow", &cluster);
    let cache = PartitionedCache::new(1 << 20);
    cache.begin_warm_partition(0);
    cache.track_puts(0);
    cache.publish_warmed_partition(0);
    let source = WarmSource::live(CHANGELOG_TOPIC, None, 0);
    let fill = FillConfig {
        chunk_offsets: 4,
        // Room for three of the chunk's four records.
        target_fraction: 35_000.0 / (1 << 20) as f64,
        ..FILL
    };

    let upper = history.len() as i64;
    let stats = fill_source(&cfg, &fill, &pools, &serving(&cache), &source, 0, upper)
        .await
        .expect("fill should succeed");

    assert_eq!((stats.end, stats.inserted), (FillEnd::Budget, 1));
    assert_eq!(version_of(&cache, 0, 4), Some(1));
    assert_eq!(version_of(&cache, 0, 1), None);
}

#[tokio::test]
async fn a_fill_stops_inside_a_chunk_once_the_cache_has_no_room() {
    let (cluster, producer) = create_mock_kafka().await;
    const PERSONS: i64 = 200;
    for person_id in 1..=PERSONS {
        produce_person_to_partition(&producer, 0, &make_person(1, person_id)).await;
    }
    let (cfg, pools) = warming_config_for("room", &cluster);
    let cache = PartitionedCache::new(1 << 20);
    cache.begin_warm_partition(0);
    cache.track_puts(0);
    cache.publish_warmed_partition(0);
    let source = WarmSource::live(CHANGELOG_TOPIC, None, 0);
    let fill = FillConfig {
        chunk_offsets: 1000,
        target_fraction: 0.01,
        ..FILL
    };

    let stats = fill_source(&cfg, &fill, &pools, &serving(&cache), &source, 0, PERSONS)
        .await
        .expect("fill should succeed");

    assert_eq!(stats.end, FillEnd::Budget);
    assert!(stats.inserted > 0 && stats.inserted < PERSONS as u64);
}

#[tokio::test]
async fn a_fill_leaves_a_person_put_since_the_warm_alone() {
    let cache = PartitionedCache::new(1 << 20);
    let (_cluster, cfg, pools, upper) = warmed_over_applied_history(&cache).await;
    let newer = personhog_leader::cache::CachedPerson::try_from(Person {
        version: 9,
        ..make_person(1, 1)
    })
    .unwrap();
    cache.put(
        0,
        PersonCacheKey {
            team_id: 1,
            person_id: 1,
        },
        newer,
    );
    // A delete released since the warm: its death document is put, then dropped once settled.
    let deleted = PersonCacheKey {
        team_id: 1,
        person_id: 2,
    };
    let death = personhog_leader::cache::CachedPerson::try_from(Person {
        version: 2,
        is_deleted: true,
        ..make_person(1, 2)
    })
    .unwrap();
    cache.put(0, deleted.clone(), death);
    cache.remove(0, &deleted);

    let source = WarmSource::live(CHANGELOG_TOPIC, None, 0);
    let one_chunk = FillConfig {
        chunk_offsets: 100,
        ..FILL
    };
    let stats = fill_source(
        &cfg,
        &one_chunk,
        &pools,
        &serving(&cache),
        &source,
        0,
        upper,
    )
    .await
    .expect("fill should succeed");

    assert_eq!(stats.records, 6);

    assert_eq!(version_of(&cache, 0, 1), Some(9));
    assert_eq!(version_of(&cache, 0, 2), None);
    assert_eq!(version_of(&cache, 0, 3), None);
}

#[tokio::test]
async fn a_fill_stops_when_the_cache_has_no_room_or_tracks_no_puts() {
    let source = WarmSource::live(CHANGELOG_TOPIC, None, 0);

    let full = PartitionedCache::new(1 << 20);
    let (_cluster, cfg, pools, upper) = warmed_over_applied_history(&full).await;
    let no_room = FillConfig {
        target_fraction: 0.0,
        ..FILL
    };
    let stats = fill_source(&cfg, &no_room, &pools, &serving(&full), &source, 0, upper)
        .await
        .expect("fill should succeed");
    assert_eq!((stats.end, stats.inserted), (FillEnd::Budget, 0));

    let untracked = PartitionedCache::new(1 << 20);
    let (_cluster, cfg, pools, upper) = warmed_over_applied_history(&untracked).await;
    serving(&untracked).stop_tracking_puts();
    let stats = fill_source(&cfg, &FILL, &pools, &serving(&untracked), &source, 0, upper)
        .await
        .expect("fill should succeed");
    assert_eq!((stats.end, stats.inserted), (FillEnd::Stopped, 0));
}

#[tokio::test]
async fn a_fill_never_inserts_into_a_later_build_of_its_partition() {
    let cache = PartitionedCache::new(1 << 20);
    let (_cluster, cfg, pools, upper) = warmed_over_applied_history(&cache).await;
    let first_build = serving(&cache);
    cache.drop_partition(0);
    cache.begin_warm_partition(0);
    cache.track_puts(0);
    cache.publish_warmed_partition(0);

    let source = WarmSource::live(CHANGELOG_TOPIC, None, 0);
    let stats = fill_source(&cfg, &FILL, &pools, &first_build, &source, 0, upper)
        .await
        .expect("fill should succeed");

    assert!(stats.inserted > 0);
    assert_eq!(version_of(&cache, 0, 1), None);
}

#[tokio::test]
async fn a_fill_over_many_chunks_reads_every_record_once() {
    let topic = common::owned_broker_topic(1).await;
    let producer = common::create_kafka_producer_on(&topic.bootstrap_servers()).await;
    const PERSONS: i64 = 200;
    for person_id in 1..=PERSONS {
        let payload = make_person(1, person_id).encode_to_vec();
        let key = format!("1:{person_id}");
        producer
            .send(
                FutureRecord::to(&topic.topic)
                    .key(&key)
                    .partition(0)
                    .payload(&payload),
                Duration::from_secs(5),
            )
            .await
            .expect("produce should succeed");
    }
    let cfg = test_warming_config("chunks", &topic.bootstrap_servers());
    let pools = WarmClientPools::new(&cfg.kafka, "chunks", &cfg.writer_consumer_group);
    let cache = PartitionedCache::new(8 << 20);
    cache.begin_warm_partition(0);
    cache.track_puts(0);
    cache.publish_warmed_partition(0);
    let source = WarmSource::live(&topic.topic, None, 0);
    let fill = FillConfig {
        chunk_offsets: 7,
        ..FILL
    };

    let stats = fill_source(&cfg, &fill, &pools, &serving(&cache), &source, 0, PERSONS)
        .await
        .expect("fill should succeed");

    assert_eq!(
        (stats.records, stats.inserted),
        (PERSONS as u64, PERSONS as u64)
    );
}

#[tokio::test]
async fn a_fill_of_several_partitions_reads_every_record_of_each_once() {
    let (cluster, producer) = create_mock_kafka().await;
    let persons_per_partition = [40_i64, 15, 3];
    for (partition, persons) in persons_per_partition.iter().enumerate() {
        for person in 1..=*persons {
            let person_id = partition as i64 * 100 + person;
            produce_person_to_partition(&producer, partition as i32, &make_person(1, person_id))
                .await;
        }
    }
    let (cfg, pools) = warming_config_for("several", &cluster);
    let cache = PartitionedCache::new(8 << 20);
    let mut fills = Vec::new();
    for (partition, persons) in persons_per_partition.iter().enumerate() {
        let partition = partition as u32;
        cache.begin_warm_partition(partition);
        cache.track_puts(partition);
        cache.publish_warmed_partition(partition);
        fills.push(PartitionFill::new(
            partition,
            cache.serving_cache(partition).expect("published"),
            WarmSource::live(CHANGELOG_TOPIC, None, partition),
            0,
            *persons,
        ));
    }
    let fill = FillConfig {
        chunk_offsets: 7,
        ..FILL
    };

    fill_to_end(&cfg, &fill, &pools, &mut fills).await;

    let filled: Vec<(u64, u64, FillEnd)> = fills
        .iter()
        .map(|filling| filling.stats().expect("the fill has ended"))
        .map(|stats| (stats.records, stats.inserted, stats.end))
        .collect();
    assert_eq!(
        filled,
        vec![
            (40, 40, FillEnd::Bound),
            (15, 15, FillEnd::Bound),
            (3, 3, FillEnd::Bound)
        ]
    );
}

#[tokio::test]
async fn the_fill_task_fills_every_queued_partition_that_still_serves() {
    let topic = common::owned_broker_topic(3).await;
    let producer = common::create_kafka_producer_on(&topic.bootstrap_servers()).await;
    for partition in 0..3 {
        let payload = make_person(1, partition as i64).encode_to_vec();
        let key = format!("1:{partition}");
        producer
            .send(
                FutureRecord::to(&topic.topic)
                    .key(&key)
                    .partition(partition)
                    .payload(&payload),
                Duration::from_secs(5),
            )
            .await
            .expect("produce should succeed");
    }
    let cfg = test_warming_config("task", &topic.bootstrap_servers());
    let pools = WarmClientPools::new(&cfg.kafka, "task", &cfg.writer_consumer_group);
    let cache = Arc::new(PartitionedCache::new(1 << 20));
    let (requests, queued) = tokio::sync::mpsc::unbounded_channel();
    for partition in 0..3 {
        cache.begin_warm_partition(partition);
        cache.track_puts(partition);
        cache.publish_warmed_partition(partition);
        let request = FillRequest {
            partition,
            cache: cache.serving_cache(partition).expect("published"),
            source: WarmSource::live(&topic.topic, None, partition),
            upper: 1,
        };
        assert!(requests.send(request).is_ok());
    }
    let released = cache.serving_cache(1).expect("published");
    cache.drop_partition(1);
    drop(requests);
    // One slot, so the last partition has to wait for the first to end.
    let one_at_a_time = FillConfig {
        concurrency: 1,
        ..FILL
    };

    let fills = Fills::new(cfg, one_at_a_time, Arc::new(pools), Arc::clone(&cache));
    tokio::time::timeout(Duration::from_secs(30), run_fills(fills, queued))
        .await
        .expect("the fill task should end once its queue is closed and drained");

    assert_eq!(
        (
            version_of(&cache, 0, 0),
            released.usage_bytes(),
            version_of(&cache, 2, 2)
        ),
        (Some(1), 0, Some(1))
    );
}

#[tokio::test]
async fn a_release_ends_a_fill_between_its_chunks() {
    let topic = common::owned_broker_topic(1).await;
    let producer = common::create_kafka_producer_on(&topic.bootstrap_servers()).await;
    for person_id in 1..=3 {
        let payload = make_person(1, person_id).encode_to_vec();
        let key = format!("1:{person_id}");
        producer
            .send(
                FutureRecord::to(&topic.topic)
                    .key(&key)
                    .partition(0)
                    .payload(&payload),
                Duration::from_secs(5),
            )
            .await
            .expect("produce should succeed");
    }
    let cfg = test_warming_config("release", &topic.bootstrap_servers());
    let pools = WarmClientPools::new(&cfg.kafka, "release", &cfg.writer_consumer_group);
    let cache = Arc::new(PartitionedCache::new(1 << 20));
    cache.begin_warm_partition(0);
    cache.track_puts(0);
    cache.publish_warmed_partition(0);
    let build = serving(&cache);
    let a_chunk_per_person = FillConfig {
        chunk_offsets: 1,
        ..FILL
    };
    let mut fills = Fills::new(cfg, a_chunk_per_person, Arc::new(pools), Arc::clone(&cache));
    fills.queue(FillRequest {
        partition: 0,
        cache: Arc::clone(&build),
        source: WarmSource::live(&topic.topic, None, 0),
        upper: 3,
    });

    fills.round().await;
    cache.drop_partition(0);
    fills.round().await;

    let filled = |person_id| {
        let key = PersonCacheKey {
            team_id: 1,
            person_id,
        };
        build.get(&key).is_some()
    };
    assert_eq!(
        (filled(3), filled(2), fills.is_idle()),
        (true, false, true),
        "only the chunk read before the release is filled, and the fill is over"
    );
}

#[tokio::test]
async fn a_fill_whose_read_stalls_ends_without_ending_the_others() {
    let (cluster, producer) = create_mock_kafka().await;
    for partition in 0..2 {
        for person in 1..=3 {
            let person_id = partition as i64 * 100 + person;
            produce_person_to_partition(&producer, partition, &make_person(1, person_id)).await;
        }
    }
    let (mut cfg, pools) = warming_config_for("stall", &cluster);
    pools.on(None).warming.warm_up(1).await;
    cfg.recv_timeout = Duration::from_secs(2);
    let cache = PartitionedCache::new(1 << 20);
    let mut fills = Vec::new();
    // Partition 0's range ends past its log, so its read can never finish.
    for (partition, upper) in [(0, 5), (1, 3)] {
        cache.begin_warm_partition(partition);
        cache.track_puts(partition);
        cache.publish_warmed_partition(partition);
        fills.push(PartitionFill::new(
            partition,
            cache.serving_cache(partition).expect("published"),
            WarmSource::live(CHANGELOG_TOPIC, None, partition),
            0,
            upper,
        ));
    }
    let one_chunk = FillConfig {
        chunk_offsets: 100,
        ..FILL
    };

    fill_to_end(&cfg, &one_chunk, &pools, &mut fills).await;

    let ended: Vec<(u64, FillEnd)> = fills
        .iter()
        .map(|filling| filling.stats().expect("the fill has ended"))
        .map(|stats| (stats.inserted, stats.end))
        .collect();
    assert_eq!(ended, vec![(0, FillEnd::Failed), (3, FillEnd::Bound)]);
}

#[tokio::test]
async fn a_fill_inserts_nothing_from_a_chunk_it_cannot_decode_and_the_others_go_on() {
    let (cluster, producer) = create_mock_kafka().await;
    // The person before the bad record must not be filled: the chunk was not read whole.
    produce_person_to_partition(&producer, 0, &make_person(1, 1)).await;
    produce_garbage_to_partition(&producer, 0).await;
    for person_id in 101..=103 {
        produce_person_to_partition(&producer, 1, &make_person(1, person_id)).await;
    }
    let (cfg, pools) = warming_config_for("undecodable", &cluster);
    let cache = PartitionedCache::new(1 << 20);
    let mut fills = Vec::new();
    for (partition, upper) in [(0, 2), (1, 3)] {
        cache.begin_warm_partition(partition);
        cache.track_puts(partition);
        cache.publish_warmed_partition(partition);
        fills.push(PartitionFill::new(
            partition,
            cache.serving_cache(partition).expect("published"),
            WarmSource::live(CHANGELOG_TOPIC, None, partition),
            0,
            upper,
        ));
    }
    let one_chunk = FillConfig {
        chunk_offsets: 100,
        ..FILL
    };

    fill_to_end(&cfg, &one_chunk, &pools, &mut fills).await;

    let ended: Vec<(u64, FillEnd)> = fills
        .iter()
        .map(|filling| filling.stats().expect("the fill has ended"))
        .map(|stats| (stats.inserted, stats.end))
        .collect();
    assert_eq!(ended, vec![(0, FillEnd::Failed), (3, FillEnd::Bound)]);
}

#[tokio::test]
async fn a_fill_fails_on_a_record_it_cannot_decode() {
    let (cluster, producer) = create_mock_kafka().await;
    produce_person_to_partition(&producer, 0, &make_person(1, 1)).await;
    produce_garbage_to_partition(&producer, 0).await;
    produce_person_to_partition(&producer, 0, &make_person(1, 2)).await;
    let (cfg, pools) = warming_config_for("garbage", &cluster);
    let cache = PartitionedCache::new(1 << 20);
    cache.begin_warm_partition(0);
    cache.track_puts(0);
    cache.publish_warmed_partition(0);
    let source = WarmSource::live(CHANGELOG_TOPIC, None, 0);

    let failed = fill_source(&cfg, &FILL, &pools, &serving(&cache), &source, 0, 3).await;

    assert!(failed.is_err());
    assert_eq!(version_of(&cache, 0, 2), None);
}
