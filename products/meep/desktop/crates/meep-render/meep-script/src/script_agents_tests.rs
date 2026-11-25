use super::*;

fn node<'a>(tree: &'a Value, id: &str) -> Option<&'a Value> {
    if tree["p"]["id"] == id {
        return Some(tree);
    }
    tree["c"]
        .as_array()
        .into_iter()
        .flatten()
        .find_map(|c| node(c, id))
}
fn labeled<'a>(tree: &'a Value, label: &str) -> Option<&'a Value> {
    if tree["p"]["label"] == label {
        return Some(tree);
    }
    tree["c"]
        .as_array()
        .into_iter()
        .flatten()
        .find_map(|c| labeled(c, label))
}
fn invoke(engine: &Engine, tree: &Value, id: &str, event: &str, value: Value) {
    let handler = node(tree, id).unwrap()["p"][event]["$fn"].as_u64().unwrap() as u32;
    engine.invoke(handler, &value).unwrap();
}

#[test]
fn agent_components_are_native_compositions_and_render_never_launches_work() {
    let engine=Engine::new(r#"view({render:()=>Page(
        Chat({id:'complete',messages:[{id:'one',role:'assistant',text:'Hello'}],onSend:()=>{}}),
        ChatComposer({id:'independent',onSend:()=>{}}),
        AgentActivity({id:'activity',blocks:[{id:'tool',kind:'tool',text:'Read',status:'completed',input:'{}',output:'Done'}]}),
        AgentPicker({id:'picker',profiles:[{id:'a',name:'An agent',available:true}],onChange:()=>{}})
    )})"#,&json!({})).unwrap();
    for _ in 0..3 {
        let tree = engine.render().unwrap();
        check_tree(&tree).unwrap();
        assert!(labeled(&tree, "History").is_none());
        assert!(labeled(&tree, "New").is_none());
        assert!(engine.take_queue().requests.is_empty());
    }
}
#[test]
fn independent_composers_keep_drafts_separate_and_send_through_callbacks() {
    let engine = Engine::new(
        r#"view({state:{sent:[]},render:()=>Page(
        ChatComposer({id:'a',onSend:text=>setState(s=>({sent:s.sent.concat('a:'+text)}))}),
        ChatComposer({id:'b',onSend:text=>setState(s=>({sent:s.sent.concat('b:'+text)}))})
    )})"#,
        &json!({}),
    )
    .unwrap();
    let tree = engine.render().unwrap();
    invoke(&engine, &tree, "a:input", "onChange", json!("first draft"));
    let tree = engine.render().unwrap();
    invoke(&engine, &tree, "b:input", "onChange", json!("other draft"));
    let tree = engine.render().unwrap();
    assert_eq!(node(&tree, "a:input").unwrap()["p"]["value"], "first draft");
    invoke(&engine, &tree, "a:input", "onSubmit", json!("first draft"));
    let tree = engine.render().unwrap();
    assert_eq!(node(&tree, "b:input").unwrap()["p"]["value"], "other draft");
    assert_eq!(
        engine.checkpoint().unwrap()["sent"],
        json!(["a:first draft"])
    );
    assert!(engine.take_queue().requests.is_empty());
}
#[test]
fn unsubscribing_stops_observation_without_cancelling_execution() {
    let engine=Engine::new(r#"let off;view({state:{seen:0},render:()=>Page(),commands:{
        watch:async()=>{off=await host.agents.subscribe('run-1',()=>setState(s=>({seen:s.seen+1})))},
        unwatch:()=>{off();}
    }})"#,&json!({})).unwrap();
    engine.command("watch", &Value::Null).unwrap();
    let q = engine.take_queue();
    assert_eq!(q.requests[0].1, "native.agents.watch");
    engine.settle(q.requests[0].0,Ok(json!({"sequence":1,"snapshot":{"id":"run-1","status":"running"},"events":[],"terminal":false}))).unwrap();
    let q = engine.take_queue();
    assert_eq!(q.requests.len(), 1);
    assert_eq!(q.requests[0].2["after"], 1);
    engine.command("unwatch", &Value::Null).unwrap();
    engine.settle(q.requests[0].0,Ok(json!({"sequence":2,"snapshot":null,"events":[{"type":"text","sequence":2,"value":{"text":"ignored"}}],"terminal":false}))).unwrap();
    assert_eq!(engine.checkpoint().unwrap()["seen"], 1);
    assert!(engine.take_queue().requests.is_empty());
}
#[test]
fn rejected_subscription_does_not_leak_a_slot_and_restore_releases_observers() {
    let engine=Engine::new(r#"view({render:()=>Page(),commands:{watch:()=>host.agents.subscribe('unknown',()=>{}).catch(()=>{})}})"#,&json!({})).unwrap();
    for _ in 0..12 {
        engine.command("watch", &Value::Null).unwrap();
        let q = engine.take_queue();
        assert_eq!(q.requests.len(), 1);
        engine
            .settle(q.requests[0].0, Err("Unknown runtime run".into()))
            .unwrap();
    }
    engine.restore(&json!({})).unwrap();
    assert!(engine.take_queue().requests.is_empty());
}
#[test]
fn tool_details_are_optional_and_do_not_discard_assistant_text() {
    let engine=Engine::new(r#"view({render:()=>Page(ChatMessage({id:'reply',showActivity:false,message:{role:'assistant',blocks:[
        {id:'t',kind:'tool',text:'Secret detail',input:'{}',output:'large'},
        {id:'a',kind:'text',text:'Useful answer'}]}}))})"#,&json!({})).unwrap();
    let tree = engine.render().unwrap();
    assert!(tree.to_string().contains("Useful answer"));
    assert!(!tree.to_string().contains("Secret detail"));
    assert!(labeled(&tree, "Copy message").is_some());
}
