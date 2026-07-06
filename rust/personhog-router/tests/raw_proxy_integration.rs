mod common;

use common::{
    create_client, create_compressed_client, create_test_person, raw_grpc_call_with_gzip_accept,
    start_test_leader, start_test_replica, start_test_replica_with_async_gzip,
    start_test_replica_with_async_gzip_disabled, start_test_router_raw,
    start_test_router_raw_with_leader, start_test_router_raw_with_leader_and_max_recv,
    start_test_router_raw_with_max_recv, TestLeaderService, TestReplicaService,
};
use personhog_proto::personhog::types::v1::{
    CheckCohortMembershipRequest, CohortMembership, DeletePersonsRequest, GetGroupsRequest,
    GetPersonByDistinctIdRequest, GetPersonRequest, GetPersonResponse,
    GetPersonsByDistinctIdsInTeamRequest, Group, GroupIdentifier, Person,
    UpdatePersonPropertiesRequest,
};
use tonic::Request;

const NUM_PARTITIONS: u32 = 8;

fn with_consistency<T>(req: T, consistency: &str) -> Request<T> {
    let mut request = Request::new(req);
    request
        .metadata_mut()
        .insert("x-read-consistency", consistency.parse().unwrap());
    request
}

// ============================================================
// 1. Replica routing — raw byte pass-through
// ============================================================

#[tokio::test]
async fn raw_proxy_eventual_get_person_routes_to_replica() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(with_consistency(
            GetPersonRequest {
                team_id: 1,
                person_id: 42,
                read_options: None,
            },
            "eventual",
        ))
        .await
        .unwrap();

    assert_eq!(response.into_inner().person.unwrap().id, test_person.id);
}

#[tokio::test]
async fn raw_proxy_get_person_default_routes_to_replica() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());
    let leader_service = TestLeaderService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: None,
        })
        .await
        .unwrap();

    assert_eq!(response.into_inner().person.unwrap().id, test_person.id);
}

#[tokio::test]
async fn raw_proxy_get_person_by_distinct_id_routes_to_replica() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person_by_distinct_id(with_consistency(
            GetPersonByDistinctIdRequest {
                team_id: 1,
                distinct_id: "test-distinct-id".to_string(),
                read_options: None,
            },
            "eventual",
        ))
        .await
        .unwrap();

    assert_eq!(response.into_inner().person.unwrap().id, test_person.id);
}

#[tokio::test]
async fn raw_proxy_get_groups_routes_to_replica() {
    let groups = vec![Group {
        id: 1,
        team_id: 1,
        group_type_index: 0,
        group_key: "company-abc".to_string(),
        group_properties: b"{}".to_vec(),
        properties_last_updated_at: vec![],
        properties_last_operation: vec![],
        created_at: 0,
        version: 1,
    }];
    let replica_service = TestReplicaService::new().with_groups(groups);
    let leader_service = TestLeaderService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_groups(with_consistency(
            GetGroupsRequest {
                team_id: 1,
                group_identifiers: vec![GroupIdentifier {
                    group_type_index: 0,
                    group_key: "company-abc".to_string(),
                }],
                read_options: None,
            },
            "eventual",
        ))
        .await
        .unwrap();

    let result = response.into_inner();
    assert_eq!(result.groups.len(), 1);
    assert_eq!(result.groups[0].group_key, "company-abc");
}

#[tokio::test]
async fn raw_proxy_check_cohort_membership_routes_to_replica() {
    let memberships = vec![CohortMembership {
        cohort_id: 1,
        is_member: true,
    }];
    let replica_service = TestReplicaService::new().with_cohort_memberships(memberships.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .check_cohort_membership(CheckCohortMembershipRequest {
            person_id: 42,
            cohort_ids: vec![1],
            read_options: None,
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert_eq!(result.memberships.len(), 1);
    assert_eq!(result.memberships[0].cohort_id, 1);
    assert!(result.memberships[0].is_member);
}

#[tokio::test]
async fn raw_proxy_delete_persons_routes_to_replica() {
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .delete_persons(DeletePersonsRequest {
            team_id: 1,
            person_uuids: vec!["00000000-0000-0000-0000-000000000042".to_string()],
        })
        .await;

    assert!(response.is_ok());
}

// ============================================================
// 2. Leader routing — typed deserialization
// ============================================================

#[tokio::test]
async fn raw_proxy_strong_get_person_routes_to_leader() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::new();
    let leader_service = TestLeaderService::new().with_person(test_person.clone());

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(with_consistency(
            GetPersonRequest {
                team_id: 1,
                person_id: 42,
                read_options: None,
            },
            "strong",
        ))
        .await
        .unwrap();

    assert_eq!(response.into_inner().person.unwrap().id, test_person.id);
}

#[tokio::test]
async fn raw_proxy_update_person_properties_routes_to_leader() {
    let test_person = create_test_person();
    let leader_service = TestLeaderService::new().with_person(test_person.clone());
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: serde_json::to_vec(&serde_json::json!({"name": "Test User"})).unwrap(),
            set_once_properties: vec![],
            unset_properties: vec![],
        })
        .await
        .unwrap();

    let result = response.into_inner();
    assert!(result.updated);
    assert_eq!(result.person.unwrap().version, test_person.version + 1);
}

#[tokio::test]
async fn raw_proxy_write_then_strong_read_roundtrip() {
    let test_person = create_test_person();
    let leader_service = TestLeaderService::new().with_person(test_person.clone());
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut client = create_client(router_addr).await;

    client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: serde_json::to_vec(&serde_json::json!({"email": "new@example.com"}))
                .unwrap(),
            set_once_properties: vec![],
            unset_properties: vec![],
        })
        .await
        .unwrap();

    let response = client
        .get_person(with_consistency(
            GetPersonRequest {
                team_id: 1,
                person_id: 42,
                read_options: None,
            },
            "strong",
        ))
        .await
        .unwrap();

    let person = response.into_inner().person.unwrap();
    assert_eq!(person.version, test_person.version + 1);

    let props: serde_json::Value = serde_json::from_slice(&person.properties).unwrap();
    assert_eq!(props["email"], "new@example.com");
}

// ============================================================
// 3. Error cases — no leader configured
// ============================================================

#[tokio::test]
async fn raw_proxy_strong_get_person_no_leader_returns_unimplemented() {
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let result = client
        .get_person(with_consistency(
            GetPersonRequest {
                team_id: 1,
                person_id: 42,
                read_options: None,
            },
            "strong",
        ))
        .await;

    assert!(result.is_err());
    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unimplemented);
    assert!(status.message().contains("leader"));
}

#[tokio::test]
async fn raw_proxy_update_person_properties_no_leader_returns_unimplemented() {
    let replica_service = TestReplicaService::new();

    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;
    let mut client = create_client(router_addr).await;

    let result = client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: vec![],
            set_once_properties: vec![],
            unset_properties: vec![],
        })
        .await;

    assert!(result.is_err());
    let status = result.unwrap_err();
    assert_eq!(status.code(), tonic::Code::Unimplemented);
    assert!(status.message().contains("leader"));
}

/// Leader-path requests must arrive uncompressed: the router scans the
/// request bytes for the routing key, which a compressed frame hides. A
/// client with send-compression enabled gets a clear UNIMPLEMENTED rather
/// than a misroute. (Compressed requests remain fully supported on the
/// replica path — see the compression tests below.)
#[tokio::test]
async fn raw_proxy_rejects_compressed_leader_requests() {
    let replica_service = TestReplicaService::new();
    let leader_service = TestLeaderService::new().with_person(create_test_person());

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr =
        start_test_router_raw_with_leader(replica_addr, leader_addr, NUM_PARTITIONS).await;
    let mut compressed = create_compressed_client(router_addr).await;

    let update_result = compressed
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            // Enough payload that tonic actually compresses the frame.
            set_properties: vec![b'x'; 4096],
            set_once_properties: vec![],
            unset_properties: vec![],
        })
        .await;
    let status = update_result.expect_err("compressed write must be rejected");
    assert_eq!(status.code(), tonic::Code::Unimplemented);
    assert!(status.message().contains("compressed"));

    let read_result = compressed
        .get_person(with_consistency(
            GetPersonRequest {
                team_id: 1,
                person_id: 42,
                read_options: None,
            },
            "strong",
        ))
        .await;
    let status = read_result.expect_err("compressed strong read must be rejected");
    assert_eq!(status.code(), tonic::Code::Unimplemented);
    assert!(status.message().contains("compressed"));
}

// ============================================================
// 4. Request body size limits
// ============================================================

#[tokio::test]
async fn raw_proxy_rejects_oversized_replica_request() {
    let replica_service = TestReplicaService::new();
    let replica_addr = start_test_replica(replica_service).await;
    // 1 KiB limit — small enough that a normal-looking request can exceed it
    let router_addr = start_test_router_raw_with_max_recv(replica_addr, 1024).await;
    let mut client = create_client(router_addr).await;

    let result = client
        .get_persons_by_distinct_ids_in_team(GetPersonsByDistinctIdsInTeamRequest {
            team_id: 1,
            distinct_ids: (0..200).map(|i| format!("distinct-id-{i:0>50}")).collect(),
            read_options: None,
        })
        .await;

    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::ResourceExhausted);
}

#[tokio::test]
async fn raw_proxy_rejects_oversized_leader_request() {
    let replica_service = TestReplicaService::new();
    let leader_service = TestLeaderService::new().with_person(create_test_person());

    let replica_addr = start_test_replica(replica_service).await;
    let leader_addr = start_test_leader(leader_service).await;
    let router_addr = start_test_router_raw_with_leader_and_max_recv(
        replica_addr,
        leader_addr,
        NUM_PARTITIONS,
        1024,
    )
    .await;
    let mut client = create_client(router_addr).await;

    let oversized_props = vec![0u8; 2048];
    let result = client
        .update_person_properties(UpdatePersonPropertiesRequest {
            team_id: 1,
            person_id: 42,
            event_name: "$set".to_string(),
            set_properties: oversized_props,
            set_once_properties: vec![],
            unset_properties: vec![],
        })
        .await;

    assert!(result.is_err());
    assert_eq!(result.unwrap_err().code(), tonic::Code::ResourceExhausted);
}

#[tokio::test]
async fn raw_proxy_accepts_request_within_limit() {
    let test_person = create_test_person();
    let replica_service = TestReplicaService::with_person(test_person.clone());
    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw_with_max_recv(replica_addr, 1024).await;
    let mut client = create_client(router_addr).await;

    let response = client
        .get_person(GetPersonRequest {
            team_id: 1,
            person_id: 42,
            read_options: None,
        })
        .await
        .unwrap();

    assert_eq!(response.into_inner().person.unwrap().id, test_person.id);
}

// ============================================================
// 5. Compression through raw proxy
// ============================================================

fn complex_properties() -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "email": "test@example.com",
        "nested": {"deeply": {"value": 42}},
        "unicode": "日本語テスト",
        "special_chars": "quotes\"and\\backslashes",
        "empty_string": "",
        "null_value": null,
        "array": [1, "two", true],
    }))
    .unwrap()
}

/// Request compression is not supported anywhere in personhog: no backend
/// enables a tonic request codec (the zstd codec that once served the typed
/// router hop is gone). On the replica path the router forwards compressed
/// frames untouched and the backend's UNIMPLEMENTED rejection relays cleanly
/// back to the client, while a plain client on the same router keeps
/// working. (The leader path rejects at the router itself — see
/// `raw_proxy_rejects_compressed_leader_requests`.)
#[tokio::test]
async fn raw_proxy_compressed_replica_request_rejected_by_backend() {
    let person = Person {
        properties: complex_properties(),
        ..create_test_person()
    };
    let replica_service = TestReplicaService::with_person(person.clone());
    let replica_addr = start_test_replica(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;

    let mut plain = create_client(router_addr).await;
    let mut compressed = create_compressed_client(router_addr).await;

    let req = || GetPersonRequest {
        team_id: 1,
        person_id: 42,
        read_options: None,
    };

    let status = compressed
        .get_person(req())
        .await
        .expect_err("compressed replica request must be rejected by the backend");
    assert_eq!(status.code(), tonic::Code::Unimplemented);

    let plain_resp = plain.get_person(req()).await.unwrap().into_inner();
    assert_eq!(plain_resp.person.unwrap().id, person.id);
}

// ============================================================
// 6. Async gzip compression
//
// These tests verify the AsyncGzipLayer by making raw gRPC requests with
// `grpc-accept-encoding: gzip` and inspecting the wire format. We bypass
// tonic's client codec because tonic's `gzip` feature is intentionally
// disabled — our layer handles gzip instead of tonic's inline compression.
// This matches production where the client is Django's grpcio.
// ============================================================

/// Decompress a gRPC frame, returning the protobuf payload.
fn decompress_grpc_frame(data: &[u8]) -> Vec<u8> {
    use flate2::read::GzDecoder;
    use std::io::Read;

    assert!(data.len() >= 5, "frame too short");
    let flag = data[0];
    let len = u32::from_be_bytes(data[1..5].try_into().unwrap()) as usize;
    assert_eq!(data.len() - 5, len, "frame length mismatch");

    if flag == 0 {
        // Uncompressed
        data[5..].to_vec()
    } else {
        // Gzip compressed
        let mut decoder = GzDecoder::new(&data[5..]);
        let mut out = Vec::new();
        decoder.read_to_end(&mut out).unwrap();
        out
    }
}

#[tokio::test]
async fn async_gzip_compresses_and_decompresses_correctly() {
    let person = Person {
        properties: complex_properties(),
        ..create_test_person()
    };
    let replica_service = TestReplicaService::with_person(person.clone());
    let replica_addr = start_test_replica_with_async_gzip(replica_service).await;

    let req = GetPersonRequest {
        team_id: 1,
        person_id: 42,
        read_options: None,
    };

    let (headers, body) = raw_grpc_call_with_gzip_accept(
        replica_addr,
        "/personhog.replica.v1.PersonHogReplica/GetPerson",
        &req,
    )
    .await;

    // Response should have grpc-encoding: gzip
    assert_eq!(headers.get("grpc-encoding").unwrap(), "gzip");

    // Frame should have compression flag set
    assert_eq!(body[0], 1, "compression flag should be set");

    // Decompress and parse the protobuf
    let decompressed = decompress_grpc_frame(&body);
    let response = <GetPersonResponse as prost::Message>::decode(decompressed.as_slice()).unwrap();
    assert_eq!(response.person.unwrap().id, 42);
}

#[tokio::test]
async fn async_gzip_through_raw_proxy() {
    let person = Person {
        properties: complex_properties(),
        ..create_test_person()
    };
    let replica_service = TestReplicaService::with_person(person.clone());
    let replica_addr = start_test_replica_with_async_gzip(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;

    let req = GetPersonRequest {
        team_id: 1,
        person_id: 42,
        read_options: None,
    };

    let (headers, body) = raw_grpc_call_with_gzip_accept(
        router_addr,
        "/personhog.service.v1.PersonHogService/GetPerson",
        &req,
    )
    .await;

    assert_eq!(headers.get("grpc-encoding").unwrap(), "gzip");
    assert_eq!(body[0], 1);

    let decompressed = decompress_grpc_frame(&body);
    let response = <GetPersonResponse as prost::Message>::decode(decompressed.as_slice()).unwrap();
    assert_eq!(response.person.unwrap().id, 42);
}

#[tokio::test]
async fn async_gzip_no_compression_without_accept_header() {
    let person = Person {
        properties: complex_properties(),
        ..create_test_person()
    };
    let replica_service = TestReplicaService::with_person(person.clone());
    let replica_addr = start_test_replica_with_async_gzip(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;

    // Plain client (no grpc-accept-encoding: gzip) through the router
    let mut plain = create_client(router_addr).await;
    let req = GetPersonRequest {
        team_id: 1,
        person_id: 42,
        read_options: None,
    };
    let resp = plain.get_person(req).await.unwrap().into_inner();
    assert_eq!(resp.person.unwrap().id, 42);
}

#[tokio::test]
async fn async_gzip_large_payload() {
    let large_props = serde_json::json!({
        "key1": "x".repeat(10_000),
        "key2": (0..100).map(|i| format!("item_{}", i)).collect::<Vec<_>>(),
        "nested": { "deep": "y".repeat(5_000) },
    });
    let person = Person {
        properties: serde_json::to_vec(&large_props).unwrap(),
        ..create_test_person()
    };
    let replica_service = TestReplicaService::with_person(person.clone());
    let replica_addr = start_test_replica_with_async_gzip(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;

    let req = GetPersonRequest {
        team_id: 1,
        person_id: 42,
        read_options: None,
    };

    let (headers, body) = raw_grpc_call_with_gzip_accept(
        router_addr,
        "/personhog.service.v1.PersonHogService/GetPerson",
        &req,
    )
    .await;

    assert_eq!(headers.get("grpc-encoding").unwrap(), "gzip");
    assert_eq!(body[0], 1);

    let decompressed = decompress_grpc_frame(&body);
    let response = <GetPersonResponse as prost::Message>::decode(decompressed.as_slice()).unwrap();
    let resp_person = response.person.unwrap();
    assert_eq!(resp_person.id, 42);
    assert_eq!(resp_person.properties, person.properties);

    // Compressed should be smaller than the uncompressed protobuf for large payloads
    let frame_payload_len = body.len() - 5;
    assert!(
        frame_payload_len < decompressed.len(),
        "compressed ({}) should be smaller than decompressed ({})",
        frame_payload_len,
        decompressed.len()
    );
}

#[tokio::test]
async fn async_gzip_disabled_flag_skips_compression() {
    let person = Person {
        properties: complex_properties(),
        ..create_test_person()
    };
    let replica_service = TestReplicaService::with_person(person.clone());
    let replica_addr = start_test_replica_with_async_gzip_disabled(replica_service).await;
    let router_addr = start_test_router_raw(replica_addr).await;

    let req = GetPersonRequest {
        team_id: 1,
        person_id: 42,
        read_options: None,
    };

    let (headers, body) = raw_grpc_call_with_gzip_accept(
        router_addr,
        "/personhog.service.v1.PersonHogService/GetPerson",
        &req,
    )
    .await;

    // No grpc-encoding header — layer is disabled
    assert!(
        headers.get("grpc-encoding").is_none(),
        "disabled layer should not set grpc-encoding"
    );

    // Frame should be uncompressed (flag=0)
    assert_eq!(body[0], 0, "compression flag should be 0 when disabled");

    // Payload is raw protobuf, should parse directly
    let payload = &body[5..];
    let response = <GetPersonResponse as prost::Message>::decode(payload).unwrap();
    assert_eq!(response.person.unwrap().id, 42);
}
