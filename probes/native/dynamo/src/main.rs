use std::io::{self, BufRead, Write};
use serde_json::{Value, json};
use dynamo_parsers::tool_calling::{ToolDefinition, parsers::detect_and_parse_tool_call_with_recovery};
use dynamo_parsers_v2::{Tool, ToolParseResult, create_tool_parser_for_family};

async fn parse(req: Value) -> Result<Value, String> {
    let dialect = req["dialect"].as_str().unwrap();
    let family = match dialect {"v4"=>"deepseek_v4", "v32"=>"deepseek_v3_2", "deepseek3"=>"deepseek_v3", "kimi"=>"kimi_k2", "qwen"=>"hermes", "qwen_coder"=>"qwen3_coder", _=>dialect};
    let tools: Vec<Tool> = req["tools"].as_array().unwrap().iter().map(|t| Tool {name:t["function"]["name"].as_str().unwrap().to_string(), description:None, parameters:t["function"]["parameters"].clone(), strict:None}).collect();
    let chunks = req["chunks"].as_array().unwrap();
    if req["mode"] == "batch" {
        let text=chunks.iter().map(|s|s.as_str().unwrap()).collect::<String>();
        let defs:Vec<ToolDefinition>=tools.iter().map(|t|ToolDefinition{name:t.name.clone(),parameters:Some(t.parameters.clone()),strict:None}).collect();
        let (calls,content)=detect_and_parse_tool_call_with_recovery(&text,Some(family),Some(&defs)).await.map_err(|e|e.to_string())?;
        return Ok(json!({"content":content.unwrap_or_default(),"reasoning":"","calls":calls.iter().map(|c|json!({"name":c.function.name,"arguments":c.function.arguments})).collect::<Vec<_>>(),"parser_generation":"v1"}));
    }
    let mut parser=create_tool_parser_for_family(family,&tools).map_err(|e|e.to_string())?;
    let mut result=ToolParseResult::default();
    for chunk in chunks { result.append(parser.push(chunk.as_str().unwrap()).map_err(|e|e.to_string())?); }
    result.append(parser.finish().map_err(|e|e.to_string())?);
    let content=result.normal_text.clone();
    let raw_deltas=result.calls.iter().map(|c|json!({"index":c.tool_index,"name":c.name,"arguments":c.arguments,"complete":c.complete})).collect::<Vec<_>>();
    let merged=result.coalesce_calls();
    Ok(json!({"content":content,"reasoning":"","calls":merged.calls.iter().map(|c|json!({"name":c.name,"arguments":c.arguments})).collect::<Vec<_>>(),"raw_deltas":raw_deltas,"parser_generation":"v2"}))
}

#[tokio::main(flavor="current_thread")]
async fn main(){
    for line in io::stdin().lock().lines(){
        let out=match line {Ok(line)=>match serde_json::from_str::<Value>(&line){Ok(req)=>match parse(req).await{Ok(out)=>out,Err(e)=>json!({"error":e})},Err(e)=>json!({"error":e.to_string()})},Err(e)=>json!({"error":e.to_string()})};
        println!("{}",out); io::stdout().flush().unwrap();
    }
}
