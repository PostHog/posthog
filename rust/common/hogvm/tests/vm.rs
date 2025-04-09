use hogvm::sync_execute;
use serde_json::Value;

#[test]
pub fn test_vm() {
    let examples = include_str!("../tests/static/bytecode_examples.jsonl");
    for (index, example) in examples.lines().enumerate() {
        println!("Executing example {}: {}", index + 1, example);
        let bytecode: Vec<Value> = serde_json::from_str(example).unwrap();
        let res = sync_execute(&bytecode, 10000);
        println!("{:?}", res);
        if let Err(res) = res {
            println!("Failed at operation {:?}", bytecode.get(res.ip));
            panic!("Example {} failed: {:?}", index + 1, res);
        }
    }
}
