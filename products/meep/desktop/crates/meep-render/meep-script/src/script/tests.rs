use super::*;

#[test]
fn validation_checks_the_render_changed_by_immediate_init() {
    for body in ["MadeUp()", "Input({value:17})"] {
        let source = format!(
            "view({{state:{{ready:false}},init(){{setState({{ready:true}})}},render:s=>s.ready?{body}:Page()}})"
        );
        assert!(
            validate(&source, &json!({})).is_err(),
            "accepted invalid post-init render: {source}"
        );
    }
}

#[test]
fn populated_preview_checks_data_dependent_and_virtual_rows() {
    for render in [
        "s.rows.map(row=>Pressable({onClick(){ }},Text(row.name)))",
        "List({id:'items',count:s.rows.length,row:i=>Pressable({},Text(s.rows[i].name))})",
    ] {
        let source = format!(
            "view({{state:{{rows:[]}},async init(){{setState({{rows:await host.call('topics','tasks',{{topic:'fixture'}})}})}},render:s=>Page({render})}})"
        );
        validate(&source, &json!({})).unwrap();
        let error = validate_populated(&source, |_| Some(json!([{"name":"One"}]))).unwrap_err();
        assert!(error.contains("Unknown element Pressable"), "{error}");
        assert_eq!(validate_populated(&source, |_| None).unwrap(), Some(false));
        let valid = source.replace("Pressable", "Box");
        assert_eq!(
            validate_populated(&valid, |_| Some(json!([{"name":"One"}]))).unwrap(),
            Some(true)
        );
    }
}

#[test]
fn populated_preview_never_resolves_other_host_operations() {
    let source = r#"view({async init(){
        host.copy('private');
        await host.call('topics','tasks',{topic:'fixture'});
        await host.cli('untrusted',[]);
    },render:()=>Page()})"#;
    let mut requests = 0;
    assert_eq!(
        validate_populated(source, |_| {
            requests += 1;
            Some(json!([]))
        })
        .unwrap(),
        Some(false)
    );
    assert_eq!(requests, 1);
}

#[test]
fn round2_motion_children_must_be_nested_on_install_and_edit() {
    for prop in [
        "keyframes:[{rotate:0},{rotate:360}]",
        "stagger:{index:0,count:1}",
    ] {
        let source = format!("view({{render:()=>Page(Icon('loader',{{{prop}}}))}})");
        let error = validate(&source, &json!({})).unwrap_err();
        assert!(error.contains("under motion"), "{error}");
        // Already saved scripts keep the historical permissive path.
        Engine::new(&source, &json!({})).unwrap().render().unwrap();
        let nested = format!("view({{render:()=>Page(Icon('loader',{{motion:{{{prop}}}}}))}})");
        validate(&nested, &json!({})).unwrap();
    }
}

#[test]
fn validation_runs_init_and_rejects_sync_and_async_failures() {
    for source in [
        "view({init(){throw Error('sync init failed')},render:()=>Page()})",
        "view({async init(){await Promise.resolve();throw Error('async init failed')},render:()=>Page()})",
    ] {
        let error = validate(source, &json!({})).unwrap_err();
        assert!(error.contains("init failed"), "{error}");
        assert!(error.contains("view.js:1:"), "{error}");
    }
}

#[test]
fn validation_summary_keeps_location_without_stack() {
    let error = validate("view({init(){\nconst items=undefined;\nthrow new TypeError('items is undefined');\n},render:()=>Page()})", &json!({})).unwrap_err();
    let summary = diagnostic_summary(&error);
    assert!(
        summary.starts_with("init threw TypeError: items is undefined (view.js:3:"),
        "{summary}"
    );
    assert!(summary.ends_with("Fix it before saving."), "{summary}");
    assert!(summary.contains("view.js:3:"));
    assert!(!summary.contains("at init"));
    assert!(!summary.contains("view-sdk"));
}

#[test]
fn validation_captures_host_effects_from_init() {
    let engine = Engine::new(
            "view({async init(){await Promise.resolve();host.focus('x');setTimeout(()=>{},1);await host.call('source','tool',{})},render:()=>Page()})",
            &json!({}),
        )
        .unwrap();
    engine.validate_init().unwrap();
    let queue = engine.take_queue();
    assert!(queue.requests.is_empty());
    assert!(queue.local.is_empty());
}

#[test]
fn prop_validation_reports_element_prop_and_source_line() {
    for (element, props, expected) in [
        ("Input", "value:42", "Input.value must be a string"),
        (
            "IconButton",
            "",
            "IconButton needs label, its accessible name",
        ),
        ("Input", "onChange:42", "Input.onChange must be a function"),
        ("Input", "placehoder:'Search'", "did you mean placeholder"),
        (
            "Tabs",
            "items:[1]",
            "Tabs.items must be an array of strings",
        ),
        (
            "Chart",
            "label:'Counts',data:'wrong'",
            "Chart.data must be an array",
        ),
    ] {
        let call = if element == "IconButton" {
            "IconButton('plus',{})".into()
        } else {
            format!("{element}({{{props}}})")
        };
        let error = validate(
            &format!("view({{render(){{\nreturn Page({call});\n}}}})"),
            &json!({}),
        )
        .unwrap_err();
        assert!(error.contains(expected), "{error}");
        assert!(error.contains("view.js:2:"), "{error}");
    }
}

#[test]
fn logo_validates_sizes_and_accepts_services_without_marks() {
    validate("view({render:()=>Page(Logo('GitHub'),Logo('Google Calendar',{size:12}),Logo('Stripe',{size:32}),Logo('slack'),Logo('mercury'),Logo('ashby'),Logo('unknown service'),Logo(''))})", &json!({})).unwrap();
    for size in ["11", "33", "-1", "0"] {
        let error = validate(
            &format!("view({{render:()=>Page(Logo('Stripe',{{size:{size}}}))}})"),
            &json!({}),
        )
        .unwrap_err();
        assert!(
            error.contains("Logo.size must be between 12 and 32"),
            "{error}"
        );
    }
    let error = validate(
        "view({render:()=>Page(Logo('Stripe',{size:'large'}))})",
        &json!({}),
    )
    .unwrap_err();
    assert!(error.contains("Logo.size must be a number"), "{error}");
}

#[test]
fn prop_validation_preserves_documented_shared_and_overloaded_types() {
    validate("view({render:()=>Page({key:1,position:'absolute',inset:0,onClick(){},hover:{bg:'inset'},cursor:'pointer'},Input({value:'ok',onChange(){}}),Avatar('Ada',{size:'large'}),Chart({label:'Count',grid:false,data:[1]}),Text('ok',{w:'50%',data:true}))})", &json!({})).unwrap();
    let names: Vec<_> = PROP_TABLE.iter().map(|(kind, _, _)| *kind).collect();
    for kind in ELEMENTS
        .iter()
        .chain(crate::script_contract::COMPONENTS.iter())
    {
        assert!(names.contains(kind), "No prop schema for {kind}");
    }
}

#[test]
fn renderer_supported_disabled_controls_validate_on_install_and_edit() {
    for expression in [
        "RadioGroup({items:['A'],value:'A',disabled:true})",
        "Rating({id:'r',label:'Rating',value:3,disabled:true})",
        "Slider({id:'s',label:'Zoom',value:20,disabled:true})",
        "Accordion({items:[{title:'T',open:false}],disabled:true},Text('Body'))",
        "RadioGroup({items:[{value:7,label:'Seven'}],value:7,disabled:true})",
        "ToolCall({id:'t',title:'Read',input:'foo',output:'bar',status:'completed'})",
        "ChatMessage({id:'m',role:'user',text:'Hello'})",
    ] {
        let source = format!("view({{render:()=>Page({expression})}})");
        validate(&source, &json!({})).unwrap();
        validate(&format!("// unrelated edit\n{source}"), &json!({})).unwrap();
    }
    for element in ["RadioGroup", "Rating", "Slider", "Accordion"] {
        let source =
            format!("view({{render:()=>Page({element}({{label:'Control',disabled:'yes'}}))}})");
        assert!(
            validate(&source, &json!({}))
                .unwrap_err()
                .contains("disabled must be true or false")
        );
    }
}

#[test]
fn missing_props_explain_their_purpose() {
    for element in ["Slider", "Rating", "Chart", "Scene"] {
        let error = validate(
            &format!("view({{render:()=>Page({element}({{}}))}})"),
            &json!({}),
        )
        .unwrap_err();
        assert!(
            error.contains(&format!(
                "{element} needs label, its accessible name (view.js:"
            )),
            "{error}"
        );
    }
    for (props, purpose) in [
        ("row:()=>Text('row')", "count, its number of rows"),
        ("count:1", "row, the function that builds a row"),
    ] {
        let error = validate(
            &format!("view({{render:()=>Page(List({{{props}}}))}})"),
            &json!({}),
        )
        .unwrap_err();
        assert!(error.contains(purpose), "{error}");
    }
}

#[test]
fn saved_views_keep_loading_with_legacy_props() {
    let source = "view({render:()=>Page(Input({value:42}),Text('legacy',{customProp:true}),IconButton('plus',{}))})";
    let engine = Engine::new(source, &json!({})).unwrap();
    check_tree(&engine.render().unwrap()).unwrap();
    assert!(validate(source, &json!({})).is_err());
}

#[test]
fn diagnostics_explain_syntax_unknown_elements_and_missing_intl() {
    for (source, expected, original) in [
        (
            "view({render:()=>Buton('Save')})",
            "did you mean Button?",
            "Buton is not defined",
        ),
        (
            "view({render:()=>Text(new Intl.NumberFormat().format(12))})",
            "Date and Number formatting recipe",
            "Intl is not defined",
        ),
        (
            "view({render( { return Page() }})",
            "Check nearby brackets",
            "JavaScript detail:",
        ),
    ] {
        let error = validate(source, &json!({})).unwrap_err();
        assert!(error.contains(expected), "{error}");
        assert!(error.contains(original), "{error}");
        assert!(
            error.lines().next().unwrap().contains("view.js:"),
            "{error}"
        );
        assert!(!diagnostic_summary(&error).contains("JavaScript detail:"));
    }
}

#[test]
fn documented_javascript_api_availability_matches_quickjs() {
    validate(r#"view({init(){
            for (const name of ['Intl','structuredClone','TextEncoder','crypto','URL']) {
                if (typeof globalThis[name] !== 'undefined') throw Error('Update the JavaScript APIs documentation: '+name);
            }
            if (typeof Date !== 'function' || typeof Map !== 'function' || typeof Promise !== 'function') throw Error('Missing documented language API');
        },render:()=>Page()})"#, &json!({})).unwrap();
}

#[test]
fn documented_formatting_recipe_runs_and_formats_edge_cases() {
    let docs = include_str!("../../agent/SCRIPT.md");
    let recipe = docs
        .split("function formatDate(value)")
        .nth(1)
        .unwrap()
        .split("\n```")
        .next()
        .unwrap();
    let source = format!("function formatDate(value){recipe}");
    validate(&source, &json!({})).unwrap();
    let engine = Engine::new(&source, &json!({})).unwrap();
    let text: String = engine.enter(|ctx| ctx.eval("JSON.stringify([formatDate('2026-11-14T10:30:00Z'),formatDate('bad'),formatNumber(12345.6),formatNumber(-12345.6),formatNumber(NaN),formatNumber(1e21),formatNumber(-1e21),formatNumber(1e100),formatNumber(-1e100),formatNumber(Number.MAX_VALUE)])")).unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&text).unwrap(),
        json!([
            "2026-11-14 UTC",
            "—",
            "12,345.60",
            "-12,345.60",
            "—",
            "1.00e+21",
            "-1.00e+21",
            "1.00e+100",
            "-1.00e+100",
            "1.80e+308"
        ])
    );
}

#[test]
fn literal_colors_warn_without_rejecting_the_view() {
    let result = validate(
        r##"view({render:()=>Page(Text('Hello',{color:'#123456'}))})"##,
        &json!({}),
    )
    .unwrap();
    assert_eq!(result["warnings"].as_array().unwrap().len(), 1);
    let result = validate(
        "view({render:()=>Page(Text('Hello',{color:'ink'}))})",
        &json!({}),
    )
    .unwrap();
    assert!(result["warnings"].as_array().unwrap().is_empty());
}

#[test]
fn sidebar_markers_accept_every_documented_shape_and_preserve_full_text() {
    for shape in ["circle", "ring", "square", "rectangle", "diamond", "star"] {
        let label = "A long pull request title ".repeat(12);
        let card = crate::sidebar::SidebarCard::normalize(
            &json!({"items":[{"label":label,"marker":{"shape":shape,"color":"accent"}}]}),
            &[],
        )
        .unwrap();
        assert_eq!(card.items[0].marker.as_ref().unwrap().shape, shape);
        assert_eq!(card.items[0].label, label.trim());
    }
}

#[test]
fn sidebar_markers_use_the_sdk_contract() {
    let engine = Engine::new(r#"view({render:()=>Page(),badge:()=>({items:[{label:'Ready',marker:{shape:'circle',color:'positive'}},{label:'Invalid',marker:{shape:'triangle',color:'red'}},{label:'Custom',marker:{shape:'rectangle',color:'#fff'}},{label:'Default',marker:{shape:'rectangle'}}]})})"#, &json!({})).unwrap();
    let card = engine.sidebar_metadata().1.unwrap();
    assert_eq!(card.items[0].marker.as_ref().unwrap().color, "positive");
    assert!(card.items[1].marker.is_none());
    assert!(card.items[2].marker.is_none());
    assert_eq!(card.items[3].marker.as_ref().unwrap().color, "secondary");
    let restored: crate::sidebar::SidebarCard =
        serde_json::from_value(json!({"items":[{"label":"Legacy"}]})).unwrap();
    assert!(restored.items[0].marker.is_none());
}

#[test]
fn badge_card_normalizes_limits_and_invalid_commands() {
    let source = r#"view({badge:()=>({value:120,title:'  Summary\nwith whitespace  ',items:[null,{label:9},{label:'Open',detail:'Detail',command:'open',args:{id:4}},{label:'Unknown',command:'missing',args:{id:5}}]}),commands:{open(){}},render:()=>Page()})"#;
    let engine = Engine::new(source, &json!({})).unwrap();
    let (badge, card) = engine.sidebar_metadata();
    assert_eq!(badge.as_deref(), Some("99+"));
    let card = card.unwrap();
    assert_eq!(card.title.as_deref(), Some("Summary with whitespace"));
    assert_eq!(card.items.len(), 2);
    assert_eq!(card.items[0].command.as_deref(), Some("open"));
    assert_eq!(card.items[0].args, Some(json!({"id":4})));
    assert_eq!(card.items[1].command, None);
    assert_eq!(card.items[1].args, None);
    let engine = Engine::new("let cycle={};cycle.self=cycle;view({badge:()=>({value:4,title:'Valid',items:[{label:'Open',command:'open',args:cycle}]}),commands:{open(){}},render:()=>Page()})", &json!({})).unwrap();
    let (badge, card) = engine.sidebar_metadata();
    assert_eq!(badge.as_deref(), Some("4"));
    assert_eq!(card.unwrap().items[0].args, None);
    let item = json!({"label":"🦊".repeat(100),"detail":"x".repeat(100),"command":"open","args":"x".repeat(1024)});
    let input = json!({"title":"界".repeat(100),"items":vec![item;10]});
    let card = crate::sidebar::SidebarCard::normalize(&input, &["open".into()]).unwrap();
    assert_eq!(card.title.as_ref().unwrap().chars().count(), 100);
    assert_eq!(card.items[0].label.chars().count(), 100);
    assert_eq!(card.items[0].detail.as_ref().unwrap().chars().count(), 100);
    assert!(card.items[0].args.is_none());
    assert_eq!(card.items.len(), 10);
    assert!(serde_json::to_vec(&card).unwrap().len() > 2048);
    let input =
        json!({"items":vec![json!({"label":"x","command":"open","args":"x".repeat(1000)});10]});
    let card = crate::sidebar::SidebarCard::normalize(&input, &["open".into()]).unwrap();
    assert_eq!(card.items.len(), 10);
    assert!(card.items.iter().all(|item| item.args.is_some()));
    let input = json!({"items":vec![json!({"label":"x"});10]});
    assert_eq!(
        crate::sidebar::SidebarCard::normalize(&input, &[])
            .unwrap()
            .items
            .len(),
        10
    );
    for value in ["4", "({value:4})", "({value:0,title:7,items:[{},null]})"] {
        let engine = Engine::new(
            &format!("view({{badge:()=>{value},render:()=>Page()}})"),
            &json!({}),
        )
        .unwrap();
        assert!(engine.sidebar_metadata().1.is_none());
    }
}

#[test]
fn badge_card_keeps_purity_and_old_saved_views_load() {
    let engine = Engine::new(
        "view({state:{n:1},badge:s=>{setState({n:2});return {title:'Oops'}},render:()=>Page()})",
        &json!({}),
    )
    .unwrap();
    assert_eq!(engine.sidebar_metadata(), (None, None));
    assert_eq!(engine.checkpoint().unwrap()["n"], 1);
}

#[test]
fn validation_warns_when_a_badge_would_be_cut() {
    let cut = validate("view({badge:()=>'17 mo',render:()=>Page()})", &json!({})).unwrap();
    assert!(cut["warnings"][0].as_str().unwrap().contains("[badge-cut]"));
    let fits = validate("view({badge:()=>'17mo',render:()=>Page()})", &json!({})).unwrap();
    assert!(!fits["warnings"].to_string().contains("badge-cut"));
}

#[test]
fn badge_normalizes_and_errors_do_not_break_render() {
    for (value, expected) in [
        ("0", None),
        ("null", None),
        ("''", None),
        ("'   '", None),
        ("1", Some("1")),
        ("99", Some("99")),
        ("100", Some("99+")),
        ("'  review  '", Some("revi")),
        ("'😀🦀🌸✨x'", Some("😀🦀🌸✨")),
    ] {
        let engine = Engine::new(
            &format!("view({{badge:()=>{value},render:()=>Page()}})"),
            &json!({}),
        )
        .unwrap();
        assert_eq!(engine.badge().as_deref(), expected, "{value}");
    }
    let engine = Engine::new(
        "view({badge(){throw Error('badge failed')},render:()=>Page()})",
        &json!({}),
    )
    .unwrap();
    assert_eq!(engine.badge(), None);
    assert!(
        engine
            .logs
            .borrow()
            .iter()
            .any(|s| s.contains("badge failed"))
    );
    assert!(engine.render().is_ok());
}
#[test]
fn fresh_badge_mutations_and_effects_are_isolated() {
    for body in [
        "s.nested.push(2);return 1",
        "getState().count=8;return 1",
        "setState({count:8});return 1",
        "host.call('x','y',{});return 1",
        "setTimeout(()=>{},1);return 1",
        "host.copy('x');return 1",
        "return Promise.resolve().then(()=>setState({count:9}))",
    ] {
        let engine = Engine::new(
            &format!(
                "view({{state:{{count:1,nested:[1]}},badge:s=>{{{body}}},render:()=>Page()}})"
            ),
            &json!({}),
        )
        .unwrap();
        engine.take_queue();
        assert_eq!(engine.badge(), None, "{body}");
        assert_eq!(
            engine.checkpoint().unwrap(),
            json!({"count":1,"nested":[1]}),
            "{body}"
        );
        let queue = engine.take_queue();
        assert!(
            !queue.dirty && queue.requests.is_empty() && queue.local.is_empty(),
            "{body}"
        );
    }
}

#[test]
fn fresh_duplicate_host_result_does_not_overwrite_newer_edits() {
    let engine=Engine::new(r#"view({state:{count:0,draft:''},render:()=>Page(),commands:{async refresh(){const r=await host.call('x','y',{});setState({count:r.count})},edit:args=>setState({draft:args.text})}})"#,&json!({})).unwrap();
    engine.background_start("refresh", &json!({})).unwrap();
    let id = engine.take_queue().requests[0].0;
    engine.command("edit", &json!({"text":"typing"})).unwrap();
    engine.settle(id, Ok(json!({"count":3}))).unwrap();
    assert_eq!(
        engine.checkpoint().unwrap(),
        json!({"count":3,"draft":"typing"})
    );
    engine.command("edit", &json!({"text":"newer"})).unwrap();
    engine.settle(id, Ok(json!({"count":1}))).unwrap();
    assert_eq!(
        engine.checkpoint().unwrap(),
        json!({"count":3,"draft":"newer"})
    );
}

#[test]
fn scripts_cannot_submit_native_workflow_failure_traces() {
    let engine = Engine::new(
        r#"view({render:()=>Page(), commands:{
                async probe() { await __native("workflows.trace", {id:"sync", trace:{}}); }
            }})"#,
        &Value::Null,
    )
    .unwrap();
    let run = engine.background_start("probe", &Value::Null).unwrap();
    assert!(engine.take_queue().requests.is_empty());
    assert_eq!(
        engine.background_result(run).unwrap()["error"],
        "Workflow traces are submitted by the native runner"
    );
}

#[test]
fn review_b_reused_background_results_do_not_complete_pending_run() {
    let engine=Engine::new("view({render:()=>Page(),commands:{first(){return 1},async refresh(){await host.call('x','y',{});return 2}}})",&json!({})).unwrap();
    let first = engine.background_start("first", &json!({})).unwrap();
    assert_eq!(engine.background_collect(first).unwrap()["done"], true);
    let second = engine.background_start("refresh", &json!({})).unwrap();
    assert_ne!(first, second);
    assert!(engine.background_result(first).is_err());
    assert_eq!(engine.background_result(second).unwrap()["done"], false);
    let request = engine.take_queue().requests[0].0;
    engine.settle(request, Ok(json!({}))).unwrap();
    assert_eq!(engine.background_collect(second).unwrap()["value"], 2);
}
#[test]
fn review_b_previous_failure_does_not_fail_next_run_or_allow_overlap() {
    let engine=Engine::new("view({render:()=>Page(),commands:{fail(){throw Error('old failure')},async refresh(){await host.call('x','y',{})}}})",&json!({})).unwrap();
    let first = engine.background_start("fail", &json!({})).unwrap();
    assert_eq!(
        engine.background_collect(first).unwrap()["error"],
        "old failure"
    );
    let second = engine.background_start("refresh", &json!({})).unwrap();
    assert_eq!(engine.background_result(second).unwrap()["done"], false);
    assert!(engine.background_start("refresh", &json!({})).is_err());
    assert!(engine.background_collect(second).is_err());
    let request = engine.take_queue().requests[0].0;
    engine.settle(request, Ok(json!({}))).unwrap();
    assert_eq!(engine.background_collect(second).unwrap()["done"], true);
    assert!(engine.background_start("refresh", &json!({})).is_ok());
}
#[test]
fn review_d_badge_retained_references_cannot_mutate_live_state() {
    let engine=Engine::new("let retained;view({state:{draft:'original',items:[1]},init(){retained=getState()},badge(){retained.draft='corrupt';retained.items.push(2);return 9},render:()=>Page()})",&json!({})).unwrap();
    engine.init().unwrap();
    engine.take_queue();
    let before = engine.checkpoint().unwrap();
    assert_eq!(engine.badge(), None);
    assert_eq!(engine.checkpoint().unwrap(), before);
    assert!(
        engine
            .logs
            .borrow()
            .iter()
            .any(|line| line.contains("badge() must not change state"))
    );
    let queue = engine.take_queue();
    assert!(!queue.dirty && queue.requests.is_empty() && queue.local.is_empty());
}

#[test]
fn needs_validation_at_install() {
    for needs in [
        json!([]),
        json!([{"source":"PostHog","tools":["exec"]},{"cli":"gh","action":["search","prs"]}]),
        json!([{"cli":"basename","action":[]}]),
        json!([{"source":"x".repeat(128),"tools":["t".repeat(128)]}]),
    ] {
        validate(
            &format!("view({{needs:{needs},render:()=>Page()}})"),
            &Value::Null,
        )
        .unwrap();
    }
    for needs in [
        json!(null),
        json!({}),
        json!([null]),
        json!([{"source":"","tools":["exec"]}]),
        json!([{"source":"PostHog","tools":[]}]),
        json!([{"source":"PostHog","tools":[1]}]),
        json!([{"cli":"gh","action":["--repo"]}]),
        json!([{"cli":"/bin/gh","action":["search","prs"]}]),
        json!([{"source":"PostHog","tools":["exec"],"cli":"gh"}]),
        // A name with a newline would draw fake rows in the approval sheet.
        json!([{"source":"x\nGitHub — Read public profile\nSlack — list_channels","tools":["t"]}]),
        json!([{"source":"PostHog","tools":["exec\r"]}]),
        json!([{"cli":"gh","action":["search\tprs"]}]),
        json!([{"cli":"gh\u{7}","action":["search"]}]),
        json!([{"source":"x".repeat(129),"tools":["exec"]}]),
        json!([{"source":"PostHog","tools":["t".repeat(129)]}]),
    ] {
        assert!(
            validate(
                &format!("view({{needs:{needs},render:()=>Page()}})"),
                &Value::Null
            )
            .is_err(),
            "{needs}"
        );
    }
}
#[test]
fn needs_mount_waits_for_single_approval_before_init() {
    let engine = Engine::new(r#"view({needs:[{source:"PostHog",tools:["exec"]},{cli:"gh",action:["search","prs"]}],init(){host.call("PostHog","exec",{})},render:()=>Page()})"#, &Value::Null).unwrap();
    assert!(engine.take_queue().requests.is_empty());
    engine.init().unwrap();
    let queue = engine.take_queue();
    assert_eq!(queue.requests.len(), 1);
    assert_eq!(queue.requests[0].1, "permissions.request");
    assert_eq!(
        queue.requests[0].2["reason"],
        "Declared by the view so it can load its data."
    );
    assert_eq!(queue.requests[0].2["needs"].as_array().unwrap().len(), 2);
    engine
        .settle(queue.requests[0].0, Ok(json!({"approved":true})))
        .unwrap();
    assert_eq!(engine.take_queue().requests[0].1, "sources.call");
}

#[test]
fn imported_needs_join_declared_ones_in_one_approval() {
    let engine = Engine::new(
        r#"view({needs:[{source:"PostHog",tools:["exec"]}],render:()=>Page()})"#,
        &Value::Null,
    )
    .unwrap();
    // One duplicate of what the script declares, one it didn't.
    engine
        .set_host_needs(
            &json!([{"source":"PostHog","tools":["exec"]},{"cli":"gh","action":["pr","list"]}]),
        )
        .unwrap();
    engine.init().unwrap();
    let queue = engine.take_queue();
    assert_eq!(queue.requests.len(), 1);
    assert_eq!(
        queue.requests[0].2["needs"],
        json!([{"source":"PostHog","tools":["exec"]},{"cli":"gh","action":["pr","list"]}])
    );
    assert_eq!(
        queue.requests[0].2["reason"],
        "What this view used where it came from, so it can load its data here."
    );
    // Nothing stored, nothing asked; something malformed is refused.
    let quiet = Engine::new("view({render:()=>Page()})", &Value::Null).unwrap();
    quiet.set_host_needs(&Value::Null).unwrap();
    quiet.init().unwrap();
    assert!(quiet.take_queue().requests.is_empty());
    assert!(
        quiet
            .set_host_needs(&json!([{"cli":"/bin/sh","action":["-c"]}]))
            .is_err()
    );
}

#[test]
fn needs_rejection_logs_and_still_initializes() {
    for error in [
        "Declared needs exceed the approval sheet's size limit",
        "This view already has permission requests waiting for the user",
        "This view generation was replaced",
    ] {
        let engine = Engine::new(r#"view({needs:[{source:"PostHog",tools:["exec"]}],state:{loading:true},init(){setState({loading:false,initialized:true})},render:()=>Page()})"#, &Value::Null).unwrap();
        engine.init().unwrap();
        let queue = engine.take_queue();
        assert_eq!(queue.requests.len(), 1);
        engine
            .settle(queue.requests[0].0, Err(error.into()))
            .unwrap();
        let state = engine.inspect().unwrap();
        assert_eq!(state["initialized"], true);
        assert_eq!(state["loading"], false);
        assert!(engine.logs.borrow().iter().any(|line| line.contains(error)));
    }
}

const COUNTER: &str = r#"
view({
  state: { count: 0, items: [] },
  render(s) {
    return Page(
      Header({ title: "Counter", subtitle: s.count + " clicks" }, Button("Add", { onClick: () => setState({ count: s.count + 1 }) })),
      List({ count: 3, row: i => Text("row " + i) }),
    );
  },
  commands: { bump(a) { setState(s => ({ count: s.count + (a.by || 1) })); return { ok: true }; } },
});
"#;

#[test]
fn renders_restores_and_handles_events() {
    let engine = Engine::new(COUNTER, &json!({"count": 4})).unwrap();
    let tree = engine.render().unwrap();
    check_tree(&tree).unwrap();
    assert_eq!(tree["c"][0]["p"]["subtitle"], "4 clicks");
    let click = tree["c"][0]["c"][0]["p"]["onClick"]["$fn"]
        .as_u64()
        .unwrap() as u32;
    engine.invoke(click, &Value::Null).unwrap();
    assert!(engine.take_queue().dirty);
    assert_eq!(engine.checkpoint().unwrap()["count"], 5);
    assert_eq!(
        engine.command("bump", &json!({"by": 10})).unwrap()["ok"],
        true
    );
    assert_eq!(engine.checkpoint().unwrap()["count"], 15);
    let row = engine.render().unwrap()["c"][1]["p"]["row"]["$fn"]
        .as_u64()
        .unwrap() as u32;
    assert_eq!(engine.row(row, 2).unwrap()["p"]["text"], "row 2");
    assert_eq!(engine.inspect().unwrap()["commands"][0], "bump");
}

#[test]
fn native_lab_actions_keep_other_buttons_stable() {
    fn buttons(tree: &Value, out: &mut std::collections::BTreeMap<String, Value>) {
        if tree["t"] == "button" || tree["t"] == "icon_button" {
            out.insert(tree["p"]["id"].as_str().unwrap().into(), tree["p"].clone());
        }
        for child in tree["c"].as_array().into_iter().flatten() {
            buttons(child, out);
        }
    }
    let controls = |engine: &Engine| {
        let mut result = std::collections::BTreeMap::new();
        buttons(&engine.render().unwrap(), &mut result);
        result
    };
    for slow in [false, true] {
        let engine =
            Engine::new(include_str!("../../agent/examples/native.js"), &Value::Null).unwrap();
        let before = controls(&engine);
        let click = before["toast-info"]["onClick"]["$fn"].as_u64().unwrap() as u32;
        engine.invoke(click, &Value::Null).unwrap();
        let queue = engine.take_queue();
        assert_eq!(queue.requests.len(), 1);
        let timer = queue
            .local
            .iter()
            .find(|(kind, _)| kind == "timer")
            .unwrap()
            .1["id"]
            .as_u64()
            .unwrap();
        let immediately = controls(&engine);
        for (id, props) in &before {
            assert_eq!(immediately[id]["label"], props["label"]);
            assert_eq!(immediately[id]["disabled"], props["disabled"]);
        }
        // Duplicate clicks are rejected immediately, before the delayed visual state.
        let click = immediately["toast-info"]["onClick"]["$fn"]
            .as_u64()
            .unwrap() as u32;
        engine.invoke(click, &Value::Null).unwrap();
        assert!(engine.take_queue().requests.is_empty());
        if slow {
            engine.fire(timer).unwrap();
            let during = controls(&engine);
            for (id, props) in &before {
                assert_eq!(during[id]["label"], props["label"]);
                assert_eq!(during[id]["disabled"], json!(id == "toast-info"));
            }
            // An unrelated action remains usable while the first request is pending.
            let other = during["toast-success"]["onClick"]["$fn"].as_u64().unwrap() as u32;
            engine.invoke(other, &Value::Null).unwrap();
            let other = engine.take_queue().requests;
            assert_eq!(other.len(), 1);
            engine
                .settle(other[0].0, Err("Test failure".into()))
                .unwrap();
        }
        engine
            .settle(queue.requests[0].0, Ok(json!({"id":"native-lab:toast"})))
            .unwrap();
        // A fast response cancels the loading timer; a late timer cannot flash controls.
        engine.fire(timer).unwrap();
        let after = controls(&engine);
        for (id, props) in &before {
            assert_eq!(after[id]["label"], props["label"]);
            assert_eq!(after[id]["disabled"], props["disabled"]);
        }
    }
}

#[test]
fn async_host_calls_resolve_through_the_queue() {
    let source = r#"
view({ state: { name: "" }, async init() { const r = await host.call("people", "who", {}); setState({ name: r.name }); }, render: s => Text(s.name) });
"#;
    let engine = Engine::new(source, &Value::Null).unwrap();
    engine.init().unwrap();
    let queue = engine.take_queue();
    assert_eq!(queue.requests.len(), 1);
    assert_eq!(queue.requests[0].1, "sources.call");
    engine
        .settle(queue.requests[0].0, Ok(json!({"name": "Ada"})))
        .unwrap();
    assert!(engine.take_queue().dirty);
    assert_eq!(engine.render().unwrap()["p"]["text"], "Ada");
}

#[test]
fn timers_keys_and_local_effects_go_through_the_queue() {
    let source = r#"
view({
  state: { ticks: 0, last: "" },
  init() { setInterval(() => setState(s => ({ ticks: s.ticks + 1 })), 10); host.copy("hi"); host.focus("search"); },
  keys: { "cmd-k": () => setState({ last: "cmd-k" }) },
  render: s => Text(s.ticks + " " + s.last),
});
"#;
    let engine = Engine::new(source, &Value::Null).unwrap();
    engine.init().unwrap();
    let queue = engine.take_queue();
    let kinds: Vec<_> = queue.local.iter().map(|(k, _)| k.as_str()).collect();
    assert_eq!(kinds, ["timer", "copy", "focus"]);
    assert_eq!(
        queue.local[0].1["ms"], 16,
        "intervals are at least one frame"
    );
    let timer = queue.local[0].1["id"].as_u64().unwrap();
    engine.fire(timer).unwrap();
    let queue = engine.take_queue();
    assert!(queue.dirty);
    assert_eq!(queue.local[0].0, "timer", "an interval re-arms itself");
    assert!(engine.key("cmd-k").unwrap());
    assert!(!engine.key("cmd-j").unwrap());
    assert_eq!(engine.render().unwrap()["p"]["text"], "1 cmd-k");
    let bad = Engine::new(
        "view({ init() { host.openUrl('file:///etc/passwd') }, render: () => Text('') })",
        &Value::Null,
    )
    .unwrap();
    assert!(bad.init().unwrap_err().contains("openUrl accepts http"));
}

#[test]
fn bundled_examples_load_render_and_expose_their_commands() {
    for name in ["inbox", "notes", "tasks", "record", "native"] {
        let source = crate::builtins::source(name).unwrap();
        validate(source, &Value::Null).unwrap_or_else(|e| panic!("{name}: {e}"));
        let engine = Engine::new(source, &Value::Null).unwrap();
        engine.init().unwrap();
        let inspected = engine.inspect().unwrap();
        assert!(
            !inspected["commands"].as_array().unwrap().is_empty(),
            "{name}"
        );
    }
    validate(RETIRED, &Value::Null).unwrap();
    // The record example validates, saves and discards through commands.
    let record = Engine::new(crate::builtins::source("record").unwrap(), &Value::Null).unwrap();
    let tree = record.render().unwrap().to_string();
    for element in [
        "\"select\"",
        "\"tabs\"",
        "\"textarea\"",
        "\"field\"",
        "\"actions\"",
    ] {
        assert!(tree.contains(element), "record renders {element}");
    }
    assert_eq!(
        record.command("reset", &Value::Null).unwrap()["saved"]["name"],
        "Milo"
    );
}

#[test]
fn errors_are_readable_and_loops_are_stopped() {
    let syntax = Engine::new("view({ render( }", &Value::Null).err().unwrap();
    assert!(syntax.contains("view.js:1"), "{syntax}");
    let missing = Engine::new("1 + 1", &Value::Null).err().unwrap();
    assert!(missing.contains("view("), "{missing}");
    let unknown = validate(
        "view({ render: () => ({ __t: 'blink', props: {}, children: [] }) })",
        &Value::Null,
    );
    assert!(unknown.unwrap_err().contains("Unknown element"));
    let looping = Engine::new("view({ render() { while (true) {} } })", &Value::Null).unwrap();
    let stopped = looping.render().unwrap_err();
    assert!(stopped.contains("500 ms"), "{stopped}");
}

#[test]
fn render_reports_the_memory_limit() {
    let hungry = Engine::new(
        &format!(
            "view({{render() {{ new ArrayBuffer({}); return Page(); }} }})",
            MEMORY + 1
        ),
        &Value::Null,
    )
    .unwrap();
    // One allocation isolates the memory limit from the loop watchdog.
    hungry.runtime.set_interrupt_handler(None);
    let error = hungry.render().unwrap_err();
    assert!(error.contains("memory"), "{error}");
}

/// Promise jobs that keep queueing jobs can't spin the thread: the entry
/// stops at its budget, and the leftover jobs never run again.
#[test]
fn endless_promise_jobs_are_stopped() {
    const BOMB: &str = "const f = () => { Promise.resolve().then(f); Promise.resolve().then(f) };";
    let started = Instant::now();
    let at_load = Engine::new(
        &format!("{BOMB} f(); view({{render:()=>Page()}})"),
        &Value::Null,
    );
    assert!(at_load.is_err());
    assert!(started.elapsed() < Duration::from_millis(1500));

    // Started from a timer, so install-time validation passes.
    let source = format!("{BOMB} view({{init(){{setTimeout(f, 10)}},render:()=>Page()}})");
    validate(&source, &Value::Null).unwrap();
    let engine = Engine::new(&source, &Value::Null).unwrap();
    engine.init().unwrap();
    let timer = engine.take_queue().local[0].1["id"].as_u64().unwrap();
    let started = Instant::now();
    let stopped = engine.fire(timer).unwrap_err();
    assert!(stopped.contains("Script stopped"), "{stopped}");
    assert!(started.elapsed() < Duration::from_millis(1500));
    // Every later entry refuses at once instead of resuming the chain.
    let started = Instant::now();
    assert!(engine.render().unwrap_err().contains("Script stopped"));
    assert!(engine.invoke(0, &Value::Null).is_err());
    assert!(started.elapsed() < Duration::from_millis(50));

    // A promise chain that ends still settles in the same entry.
    let finite = Engine::new(
            "view({state:{n:0},init(){let n=0;const step=()=>{if(++n<10000)Promise.resolve().then(step);else setState({n})};step()},render:()=>Page()})",
            &Value::Null,
        )
        .unwrap();
    finite.init().unwrap();
    assert_eq!(finite.checkpoint().unwrap()["n"], 10000);
}
