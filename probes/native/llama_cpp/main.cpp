#include "chat.h"
#include "chat-auto-parser.h"
#include "parsers/parsers.h"
#include "json.h"
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>

using json = common_json;
static json render(const common_chat_msg & msg) {
    json calls = json::array();
    for (const auto & call : msg.tool_calls) calls.push_back({{"name", call.name}, {"arguments", call.arguments}});
    return {{"content", msg.content}, {"reasoning", msg.reasoning_content}, {"calls", calls}};
}
static json run(const json & req) {
    static std::map<std::string, common_chat_templates_ptr> templates;
    const std::map<std::string, std::string> files = {
        {"v32", "deepseek-ai-DeepSeek-V3.2.jinja"}, {"v4", "deepseek-ai-DeepSeek-V4.jinja"},
        {"kimi", "Kimi-K2-Thinking.jinja"}, {"qwen", "Qwen-Qwen3-0.6B.jinja"}, {"qwen_coder", "Qwen3-Coder.jinja"}
    };
    const std::string dialect = req.at("dialect");
    if (!templates.count(dialect)) {
        std::ifstream file("sources/llama_cpp/models/templates/" + files.at(dialect));
        if (!file) throw std::runtime_error("Missing upstream template");
        std::stringstream buffer; buffer << file.rdbuf();
        templates.emplace(dialect, common_chat_templates_init(nullptr, buffer.str()));
    }
    common_chat_templates_inputs inputs;
    common_chat_msg user; user.role = "user"; user.content = "Parser replay";
    inputs.messages = {user};
    inputs.enable_thinking = req.contains("thinking") ? req["thinking"].get<bool>() : false;
    inputs.reasoning_format = (req.contains("rf") && req["rf"] == "deepseek") ? COMMON_REASONING_FORMAT_DEEPSEEK : COMMON_REASONING_FORMAT_NONE;
    inputs.parallel_tool_calls = true;
    inputs.tool_choice = COMMON_CHAT_TOOL_CHOICE_AUTO;
    for (const auto & item : req.at("tools")) {
        const auto & fn = item.at("function");
        inputs.tools.push_back({fn.at("name"), "Inert fixture", fn.at("parameters").dump()});
    }
    common_chat_session session(templates.at(dialect).get(), nullptr, inputs);
    json partial = json::array();
    try {
        if (req.at("mode") == "batch") {
            std::string text;
            for (const auto & chunk : req.at("chunks")) text += chunk.get<std::string>();
            session.finish(common_chat_input(text));
        } else {
            for (const auto & chunk : req.at("chunks")) {
                session.feed(common_chat_input(chunk.get<std::string>()));
                partial.push_back(render(session.msg()));
            }
            session.finish();
        }
    } catch (const std::exception & error) {
        return {{"error", error.what()}, {"partial_snapshots", partial}};
    }
    auto out = render(session.msg());
    out["format"] = common_chat_format_name(session.format());
    return out;
}
int main() {
    std::string line;
    while (std::getline(std::cin, line)) {
        try { std::cout << run(json::parse(line)).dump() << std::endl; }
        catch (const std::exception & error) { std::cout << json({{"error", error.what()}}).dump() << std::endl; }
    }
}
