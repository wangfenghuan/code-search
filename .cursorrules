# Code Search & Architecture MCP Guidelines (启发自 CodeGraph)

本项目已接入 `code-search-mcp` 本地代码知识图谱与语义检索服务。在探索、重构和编写代码时，请遵循以下规则以节省 Token 与最大化准确率：

## 1. 探索与定位
- **了解全貌**: 优先调用 `get_codebase_outline()` 查看全局多语言架构地图，了解各模块核心职责，避免盲目全盘搜索。
- **业务全链路**: 询问业务功能（如“用户认证流程”、“支付退款逻辑”）时，**优先且仅需调用一次** `explore_codebase(query=...)`，直接获得包含路由入口、核心源码与下游拓扑的端到端报告。
- **概念/意图搜索**: 当不知道确切函数名时，使用 `search_codebase(query=...)`，默认以 `compact` 紧凑模式返回代码摘要。
- **字面量/配置项搜索**: 已知确切标识符、错误码、环境变量 Key 时，使用 `exact_search(pattern=...)`，基于 ripgrep 秒级定位。

## 2. 重构与改动保护（防线上故障）
- **影响面评估**: 在修改或重构任何重要函数/类前，**必须先调用** `get_impact_radius(symbol_name=...)`，获取直接和间接波及的上游模块、关联文件与对外 Web 路由。
- **调用拓扑追踪**: 
  - 追踪谁调用了目标函数：`get_symbol_callers(symbol_name=...)`
  - 追踪目标函数依赖了谁：`get_symbol_callees(symbol_name=...)`
  - 全仓库反向引用分析：`find_references(symbol_name=...)`

## 3. Token 极省最佳实践
- 严禁对大文件全量读取；若需查看某段函数完整实现，配合 `get_file_content(path, start_line, end_line)` 按需精准提取行区间。
