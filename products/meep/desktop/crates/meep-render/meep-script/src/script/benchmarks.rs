use super::*;

/// `cargo test -p meep-script script_dataset_bench -- --ignored --nocapture`:
/// the Showcase's ingest and search, timed from inside the script as it does.
#[test]
#[ignore]
fn script_dataset_bench() {
    let engine = Engine::new(r#"
const F=["Ada","Grace","Alan","Linus","Margaret","Ken","Barbara","Dennis","Frances","Edsger","Radia","Bjarne","Hedy","Guido","Katherine","Niklaus"];
const L=["Lovelace","Hopper","Turing","Torvalds","Hamilton","Thompson","Liskov","Ritchie","Allen","Dijkstra","Perlman","Stroustrup","Lamarr","van Rossum","Johnson","Wirth","Kay"];
const T=["Compilers","Graphics","Networking","Storage","Kernel","Design","Research"], S=["Ready","Pending","Failed"];
const row=i=>({id:i+1,name:F[i%16]+" "+L[(i*7)%17],team:T[(i*3)%7],status:S[(i*13)%3],score:((i*7919)%10000)/100});
view({render:()=>Page(),commands:{
  load({c}){const rows=[];for(let i=c*10000;i<(c+1)*10000;i++)rows.push(row(i));
    let t=Date.now();const json=JSON.stringify({rows});const stringify=Date.now()-t;
    t=Date.now();if(c===0)host.data.set("bench",rows,{key:"id"});else host.data.patch("bench",rows);
    return {host:Date.now()-t,stringify};},
  rust({q}){const query={text:{value:q,fields:["name","team","status"]}};let n=0,m=0,t=Date.now();
    do{m=host.data.count("bench",query);n++;}while(Date.now()-t<100);return {ms:(Date.now()-t)/n,m};},
  js({q,from}){const rows=[];for(let i=from;i<from+20000;i++)rows.push(row(i));const t=Date.now();
    const m=rows.filter(r=>r.name.toLowerCase().includes(q)||r.team.toLowerCase().includes(q)||r.status.toLowerCase().includes(q)).length;
    return {ms:Date.now()-t,m};},
}});"#, &json!({})).unwrap();
    let (mut host, mut stringify) = (0, 0);
    for c in 0..10 {
        let r = engine.command("load", &json!({"c":c})).unwrap();
        host += r["host"].as_u64().unwrap();
        stringify += r["stringify"].as_u64().unwrap();
    }
    eprintln!(
        "\nSCRIPT DATASET BENCH debug_assertions={}",
        cfg!(debug_assertions)
    );
    eprintln!(
        "  ingest, host calls as timed by the view: {host} ms (JSON.stringify alone: {stringify} ms)"
    );
    let rust = engine.command("rust", &json!({"q":"ada"})).unwrap();
    let mut js = (0, 0);
    for from in (0..100000).step_by(20000) {
        let r = engine
            .command("js", &json!({"q":"ada","from":from}))
            .unwrap();
        js.0 += r["ms"].as_u64().unwrap();
        js.1 += r["m"].as_u64().unwrap();
    }
    eprintln!(
        "  search 'ada', Rust dataset: {:.3} ms ({} rows)",
        rust["ms"].as_f64().unwrap(),
        rust["m"]
    );
    eprintln!(
        "  search 'ada', QuickJS Array.filter: {} ms ({} rows)",
        js.0, js.1
    );
}

/// `MEEP_PERF_CAPTURE=DIR cargo test -p meep-script render_split_bench -- --ignored --nocapture`:
/// where a captured view's render time goes, from inside the engine.
#[test]
#[ignore]
fn render_split_bench() {
    let Ok(dir) = std::env::var("MEEP_PERF_CAPTURE") else {
        return;
    };
    let dir = std::path::Path::new(&dir);
    let source = std::fs::read_to_string(dir.join("view.js")).unwrap();
    let state: Value = std::fs::read_to_string(dir.join("state.json"))
        .unwrap()
        .parse()
        .unwrap();
    let probe = r#"
const __benchView = view;
view = (d) => __benchView(Object.assign({}, d, { commands: Object.assign({}, d.commands || {}, { __split() {
  const s = getState(), n = 50, now = () => Date.now();
  let t = now(); let tree; for (let i = 0; i < n; i++) tree = __def.render(s); const render = (now() - t) / n;
  t = now(); let out; for (let i = 0; i < n; i++) { __handlers.clear(); out = __emit(tree); } const emit = (now() - t) / n;
  t = now(); let text; for (let i = 0; i < n; i++) text = JSON.stringify(out); const stringify = (now() - t) / n;
  return { render, emit, stringify, bytes: text.length };
} }) }));
"#;
    let engine = Engine::new(&format!("{probe}\n{source}"), &state).unwrap();
    engine.data.borrow_mut().load(
        std::fs::read_to_string(dir.join("datasets.json"))
            .map(|t| t.parse().unwrap())
            .unwrap_or(Value::Null),
    );
    let split = engine.command("__split", &Value::Null).unwrap();
    let t = Instant::now();
    for _ in 0..50 {
        std::hint::black_box(engine.render().unwrap());
    }
    eprintln!("\nRENDER SPLIT {} {split}", dir.display());
    eprintln!(
        "  whole Engine::render (JS + JSON parse in Rust): {:.3} ms",
        t.elapsed().as_secs_f64() * 1000. / 50.
    );
}
