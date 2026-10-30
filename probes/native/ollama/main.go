package main

import (
 "bufio"
 "encoding/json"
 "fmt"
 "os"
 "strings"
 "github.com/ollama/ollama/api"
 "github.com/ollama/ollama/tools"
 p "infra-replay/parsers"
)

type Request struct { Dialect string `json:"dialect"`; Mode string `json:"mode"`; Chunks []string `json:"chunks"`; Tools []api.Tool `json:"tools"` }
type Call struct { Name string `json:"name"`; Arguments any `json:"arguments"` }
type Result struct { Content string `json:"content"`; Reasoning string `json:"reasoning"`; Calls []Call `json:"calls"`; Error string `json:"error,omitempty"`; Path string `json:"parser_path"` }
type Parser interface { Init([]api.Tool,*api.Message,*api.ThinkValue) []api.Tool; Add(string,bool)(string,string,[]api.ToolCall,error) }

func run(req Request) Result {
 out:=Result{Calls:[]Call{}}
 var parser Parser
 switch req.Dialect {
 case "deepseek3": parser=&p.DeepSeek3Parser{};out.Path="native_deepseek3"
 case "qwen": parser=&p.Qwen3Parser{};out.Path="native_qwen3"
 case "qwen_coder": parser=&p.Qwen3CoderParser{};out.Path="native_qwen3_coder"
 case "kimi":
  legacy:=tools.NewParserWithTag(req.Tools,"<|tool_calls_section_begin|>")
  out.Path="explicit_template_tag_legacy_parser"
  for _,chunk:=range req.Chunks {calls,content:=legacy.Add(chunk);out.Content+=content;for _,c:=range calls {out.Calls=append(out.Calls,Call{c.Function.Name,c.Function.Arguments})}}
  return out
 case "qwen_coder_generic":
 legacy:=tools.NewParserWithTag(req.Tools,"<tool_call>")
 out.Path="generic_template_tag_parser"
 for _,chunk:=range req.Chunks {calls,content:=legacy.Add(chunk);out.Content+=content;for _,c:=range calls {out.Calls=append(out.Calls,Call{c.Function.Name,c.Function.Arguments})}}
 return out
 case "v32","v4","v41":
  // A passthrough control: this snapshot has no native DSML parser registered.
  out.Path="no_native_dsml_parser_registered";out.Content=strings.Join(req.Chunks,"");return out
 default:out.Error="unsupported dialect";return out
 }
 parser.Init(req.Tools,nil,nil)
 for i,chunk:=range req.Chunks {
  content,thinking,calls,err:=parser.Add(chunk,i==len(req.Chunks)-1)
  out.Content+=content;out.Reasoning+=thinking
  for _,c:=range calls {out.Calls=append(out.Calls,Call{c.Function.Name,c.Function.Arguments})}
  if err!=nil {out.Error=err.Error();return out}
 }
 return out
}

func main(){
 scanner:=bufio.NewScanner(os.Stdin);scanner.Buffer(make([]byte,4096),4000000)
 for scanner.Scan(){var req Request;if err:=json.Unmarshal(scanner.Bytes(),&req);err!=nil {fmt.Println(`{"error":"bad input"}`);continue};out:=run(req);b,_:=json.Marshal(out);fmt.Println(string(b))}
}
