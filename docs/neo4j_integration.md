# Neo4j 图数据库集成 - 功能文档

## 一、功能概述

本次更新为 Strix 添加了 Neo4j 图数据库集成，实现了安全测试发现的持久化存储、跨会话共享和自动上下文注入。

---

## 二、新增功能

### 2.1 Neo4j 图数据库集成

| 功能 | 说明 | 文件 |
|------|------|------|
| **Neo4j 客户端** | 连接和管理 Neo4j 数据库 | `strix/memory/neo4j_client.py` |
| **自动存储漏洞** | 发现漏洞时自动存储到 Neo4j | `strix/telemetry/tracer.py` |
| **自动存储发现** | 工具执行后自动存储 Endpoint/Service/Credential | `strix/tools/executor.py` |
| **自动注入上下文** | 每次对话自动注入 `<neo4j_context>` | `strix/llm/memory_compressor.py` |
| **主动查询工具** | LLM 可调用 `query_memory` 查询历史发现 | `strix/tools/memory/memory_actions.py` |

---

### 2.2 数据存储能力

| 节点类型 | 存储触发 | 关系建立 |
|---------|---------|---------|
| **Target** | 自动（伴随其他存储） | - |
| **Vulnerability** | 自动（发现漏洞时） | ✅ 自动关联到正确 Target |
| **Endpoint** | 自动（浏览器访问时） | ✅ 自动关联到对应 Target |
| **Service** | 自动（端口扫描时） | ✅ 自动关联到对应 Target |
| **Credential** | 自动（检测到凭证时） | ✅ 自动关联到对应 Target |
| **Technology** | LLM 主动存储 | ✅ 自动关联（如果有 URL） |

---

## 三、能力扩展

| 能力 | 修改前 | 修改后 |
|------|--------|--------|
| **知识持久化** | ❌ 会话结束即消失 | ✅ 跨会话持久化存储 |
| **跨 Agent 共享** | ❌ 不支持 | ✅ 所有 Agent 共享同一知识库 |
| **避免重复工作** | ❌ 无记忆 | ✅ 自动读取历史发现 |
| **目标隔离** | ❌ 无隔离 | ✅ 按 Target 分类存储 |
| **阶段判断** | ❌ 无 | ✅ 自动判断当前阶段（recon/scanning/exploitation/post-exploitation） |
| **上下文注入** | ❌ 无 | ✅ 自动注入 `<neo4j_context>` |

---

## 四、修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `strix/memory/neo4j_client.py` | Neo4j 客户端，存储/查询方法 |
| `strix/telemetry/tracer.py` | 漏洞自动存储，避免混装 |
| `strix/tools/executor.py` | 工具执行后自动存储发现 |
| `strix/llm/memory_compressor.py` | 自动注入 `<neo4j_context>` |
| `strix/tools/memory/` | `query_memory` 工具 |
| `strix/tools/__init__.py` | 导入 memory 模块 |
| `strix/agents/StrixAgent/system_prompt.jinja` | `<neo4j_memory>` 提示词 |

---

## 五、数据流架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Neo4j 集成架构                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│  │ 浏览器工具   │    │ 终端工具    │    │ Python 工具 │                     │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                     │
│         │                  │                  │                             │
│         └──────────────────┼──────────────────┘                             │
│                            │                                                │
│                            ▼                                                │
│                   executor.py: _auto_store_discovery()                      │
│                            │                                                │
│                            ▼                                                │
│                   ┌─────────────────┐                                       │
│                   │  Neo4j 数据库    │                                       │
│                   │  - Target       │                                       │
│                   │  - Endpoint     │                                       │
│                   │  - Vulnerability│                                       │
│                   │  - Technology   │                                       │
│                   │  - Credential   │                                       │
│                   └────────┬────────┘                                       │
│                            │                                                │
│                            ▼                                                │
│            memory_compressor.py: _get_target_topology()                     │
│                            │                                                │
│                            ▼                                                │
│                   <neo4j_context> 自动注入                                   │
│                            │                                                │
│                            ▼                                                │
│                   ┌─────────────────┐                                       │
│                   │    LLM 上下文    │                                       │
│                   └─────────────────┘                                       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 六、使用场景

| 场景 | 效果 |
|------|------|
| **新会话开始** | 自动读取历史发现，避免重复扫描 |
| **多目标测试** | 按 Target 隔离，不会混淆 |
| **跨 Agent 协作** | 共享知识库，避免重复工作 |
| **阶段恢复** | 自动判断阶段，继续之前的工作 |
| **主动查询** | LLM 可调用 `query_memory` 查询特定信息 |

---

## 七、核心代码逻辑

### 7.1 自动存储流程

```python
# executor.py
async def _execute_single_tool(...):
    result = await execute_tool_invocation(tool_inv, agent_state)
    
    # 工具执行后自动存储发现
    if not is_error and tracer:
        _auto_store_discovery(tool_name, args, result, tracer)
```

### 7.2 自动注入流程

```python
# memory_compressor.py
def compress_history(self, messages):
    # 始终注入 Neo4j 拓扑信息
    topology_context = self._get_target_topology()
    if topology_context:
        topology_msg = {
            "role": "system",
            "content": topology_context,  # <neo4j_context> 内容
        }
        system_msgs.append(topology_msg)
```

### 7.3 关系自动建立

```python
# neo4j_client.py
def store_finding(self, node_type, properties, relationships):
    # 创建节点
    session.run(f"CREATE (n:{node_type} $props)", props=properties)
    
    # 自动从 URL 提取 Target 并建立关系
    url = properties.get("url") or properties.get("path")
    if url and url.startswith("http"):
        base_url = extract_base_url(url)
        self.store_target(base_url)
        session.run(f"MATCH (n:{node_type}) MATCH (t:Target) MERGE (n)-[:DISCOVERED_IN]->(t)")
```

---

## 八、配置要求

### 8.1 Neo4j 容器启动

```bash
docker run -d \
  --name strix-neo4j-memory \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/strixpassword \
  -e NEO4J_PLUGINS='["apoc"]' \
  neo4j:latest
```

### 8.2 Python 依赖

```bash
pip install neo4j
```

---

## 九、与 Agent Graph 的区别

| 系统 | 数据来源 | 存储内容 | 用途 |
|------|---------|---------|------|
| **Agent Graph** | 内存变量 | Agent 委托关系、任务状态 | 管理 Agent 协作 |
| **Neo4j Memory** | Neo4j 数据库 | 安全测试发现 | 存储和查询安全知识 |

两者独立运作，互不冲突，互补使用。

---

## 十、日志输出

### 10.1 存储日志

```
[Neo4j] ✅ Auto-stored Endpoint from browser: /api/login
[Neo4j] ✅ Auto-stored Services from terminal: 3 ports
[Neo4j] ✅ Auto-stored Credential from python: token
```

### 10.2 查询日志

```
[Neo4j] 📖 Retrieved graph memory for http://example.com: 4 items, phase=post-exploitation
[Neo4j] 🔍 Queried graph memory for 'endpoints': found 2 results
```

---

## 十一、未来扩展方向

1. **可视化界面**：集成 Neo4j Browser 展示攻击图谱
2. **攻击路径分析**：基于图数据库分析攻击路径
3. **知识推理**：利用图算法进行安全知识推理
4. **多项目隔离**：支持多项目/多用户的数据隔离
