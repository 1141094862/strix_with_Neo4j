# Agent 逻辑结构与 Docker 环境交互分析

## 1. 系统概述

Strix 是一个基于代理（Agent）的自动化安全扫描系统，通过 Docker 容器提供隔离的运行环境，实现安全扫描任务的执行。本文档详细分析了 Strix 中 Agent 的逻辑结构、核心功能模块、数据流向以及与 Docker 环境的交互机制。

## 2. Agent 核心结构

### 2.1 类层次结构

```
+------------------+
|   AgentMeta      |  # 元类，用于动态加载 Agent 配置
+------------------+
        ^
        |
+------------------+
|   BaseAgent      |  # 所有 Agent 的基类
+------------------+
        ^
        |
+------------------+
|   StrixAgent     |  # 具体的 Agent 实现
+------------------+
```

### 2.2 核心类定义

#### 2.2.1 AgentMeta

**文件路径**: `strix/agents/base_agent.py`

AgentMeta 是一个元类，用于动态加载 Agent 的 Jinja 环境和配置。它在 Agent 类创建时自动初始化 Jinja 环境，用于加载和渲染 Agent 的提示模板。

#### 2.2.2 BaseAgent

**文件路径**: `strix/agents/base_agent.py`

BaseAgent 是所有 Agent 的基类，定义了 Agent 的核心逻辑和生命周期管理。主要功能包括：
- Agent 初始化和配置
- 对话历史管理
- LLM 交互
- 工具执行
- 沙箱管理
- 错误处理和恢复

#### 2.2.3 StrixAgent

**文件路径**: `strix/agents/StrixAgent/strix_agent.py`

StrixAgent 是具体的 Agent 实现，继承自 BaseAgent，主要负责：
- 扫描配置的解析和处理
- 目标资源的管理
- 扫描任务的执行

#### 2.2.4 AgentState

**文件路径**: `strix/agents/state.py`

AgentState 管理 Agent 的状态信息，包括：
- Agent 基本信息（ID、名称、父 ID）
- 沙箱信息（ID、令牌、URL）
- 任务信息（任务描述、迭代次数、最大迭代次数）
- 执行状态（已完成、停止请求、等待输入、LLM 失败）
- 对话历史、动作记录、观察结果和错误信息

## 3. Agent 核心功能模块

### 3.1 初始化与配置

**功能**: 初始化 Agent 实例，加载配置，设置 LLM 客户端，创建 Agent 状态。

**关键代码**: 
- `BaseAgent.__init__()`: 初始化 Agent 实例
- `_initialize_sandbox_and_state()`: 初始化沙箱和状态

### 3.2 主循环（agent_loop）

**功能**: Agent 的主循环，处理 Agent 的整个生命周期。

**流程**: 
1. 初始化沙箱和状态
2. 检查 Agent 消息
3. 处理等待输入状态
4. 检查是否需要停止
5. 处理 LLM 失败情况
6. 增加迭代次数
7. 检查是否接近最大迭代次数
8. 处理单轮迭代（LLM 调用 + 工具执行）
9. 处理错误和异常

### 3.3 LLM 交互

**功能**: 与 LLM 进行交互，生成响应和工具调用。

**关键代码**: 
- `_process_iteration()`: 调用 LLM 生成响应
- `llm.generate()`: 发送请求给 LLM

### 3.4 工具执行

**功能**: 执行 LLM 生成的工具调用。

**关键代码**: 
- `_execute_actions()`: 执行工具调用
- `process_tool_invocations()`: 处理工具调用

### 3.5 状态管理

**功能**: 管理 Agent 的状态流转。

**关键状态转换**: 
- 运行中 → 等待输入
- 等待输入 → 运行中
- 运行中 → 已完成
- 运行中 → 错误

### 3.6 错误处理与恢复

**功能**: 处理执行过程中的各种错误，包括 LLM 请求失败、工具执行错误等。

**关键代码**: 
- `_handle_iteration_error()`: 处理迭代错误
- `LLMRequestFailedError` 处理: 处理 LLM 请求失败

## 4. 数据流向

```
+----------------+     +----------------+     +----------------+     +----------------+
|   用户输入     |     |   AgentState   |     |      LLM       |     |   工具调用     |
+----------------+     +----------------+     +----------------+     +----------------+
        |                      |                      |                      |
        | 1. 设置任务          |                      |                      |
        +-------------------> |                      |                      |
                               | 2. 获取对话历史      |                      |
                               +-------------------> |                      |
                                                      | 3. 生成响应          |
                                                      +-------------------> |
                                                                             | 4. 执行工具  |
                                                                             +----------------+
                                                                                     |
                                                                                     | 5. 返回结果  |
                                                                                     |
+----------------+     +----------------+     +----------------+     +----------------+
|   结果输出     | <--- |   AgentState   | <--- |      LLM       | <--- |   工具结果     |
+----------------+     +----------------+     +----------------+     +----------------+
```

## 5. Docker 环境交互机制

### 5.1 运行时架构

```
+------------------+
|   主进程         |
|  (strix-cli)     |
+------------------+
        |
        | 1. 创建/获取容器
        v
+------------------+
|  DockerRuntime   |
|  (管理容器)      |
+------------------+
        |
        | 2. 初始化容器
        v
+------------------+
|   Docker 容器    |
|  (strix-sandbox) |
+------------------+
        |
        | 3. 启动工具服务器
        v
+------------------+
|  Tool Server     |
|  (uvicorn + fastapi) |
+------------------+
        |
        | 4. 注册 Agent
        v
+------------------+
|  Agent 进程      |
|  (执行工具)      |
+------------------+
```

### 5.2 核心组件

#### 5.2.1 DockerRuntime

**文件路径**: `strix/runtime/docker_runtime.py`

DockerRuntime 实现了 `AbstractRuntime` 接口，负责管理 Docker 容器的生命周期：
- 创建/获取扫描容器
- 初始化容器（Caido 代理 + 工具服务器）
- 复制本地资源到容器
- 管理容器的启动和停止

#### 5.2.2 Tool Server

**文件路径**: `strix/runtime/tool_server.py`

Tool Server 是运行在 Docker 容器内的 HTTP 服务器，负责处理工具调用请求：
- 提供 REST API 接口
- 验证请求的合法性
- 为每个 Agent 创建独立的进程
- 执行工具调用并返回结果

### 5.3 交互流程

1. **创建沙箱**: 
   - Agent 调用 `runtime.create_sandbox()`
   - DockerRuntime 检查是否存在现有容器，不存在则创建新容器
   - 容器启动后，初始化 Caido 代理和工具服务器
   - 复制本地资源到容器

2. **注册 Agent**: 
   - Agent 调用工具服务器的 `/register_agent` 接口
   - 工具服务器为 Agent 创建独立的进程和队列

3. **执行工具**: 
   - Agent 调用工具服务器的 `/execute` 接口
   - 工具服务器将请求放入对应的 Agent 队列
   - Agent 进程从队列中获取请求，执行工具
   - 执行结果通过队列返回给工具服务器
   - 工具服务器将结果返回给 Agent

4. **销毁沙箱**: 
   - Agent 调用 `runtime.destroy_sandbox()`
   - DockerRuntime 停止并删除容器

### 5.4 通信协议

- **协议类型**: HTTP/REST API
- **认证方式**: Bearer 令牌
- **API 端点**:
  - `/register_agent`: 注册 Agent
  - `/execute`: 执行工具
  - `/health`: 健康检查

### 5.5 资源调度

- **容器隔离**: 每个扫描任务在独立的 Docker 容器中执行
- **进程隔离**: 每个 Agent 在容器内有独立的进程
- **工具隔离**: 工具执行在独立的子进程中进行
- **端口管理**: 动态分配可用端口，避免冲突

## 6. 关键配置参数

| 配置参数              | 描述                          | 默认值                  | 来源                     |
|---------------------|-------------------------------|------------------------|--------------------------|
| STRIX_SANDBOX_MODE  | 是否启用沙箱模式              | false                  | 环境变量                 |
| STRIX_IMAGE         | Docker 镜像名称               | ghcr.io/usestrix/strix-sandbox:0.1.10 | 环境变量 |
| TOOL_SERVER_PORT    | 工具服务器端口                | 动态分配                | 容器环境变量             |
| TOOL_SERVER_TOKEN   | 工具服务器认证令牌            | 随机生成                | 容器环境变量             |
| CAIDO_PORT          | Caido 代理端口                | 动态分配                | 容器环境变量             |
| CAIDO_API_TOKEN     | Caido API 令牌                | 自动生成                | 容器内部                 |
| max_iterations      | Agent 最大迭代次数            | 300                    | 代码配置                 |

## 7. 核心算法逻辑

### 7.1 Agent 主循环算法

```python
async def agent_loop(self, task: str) -> dict[str, Any]:
    # 初始化沙箱和状态
    await self._initialize_sandbox_and_state(task)
    
    while True:
        # 检查 Agent 消息
        self._check_agent_messages(self.state)
        
        # 处理等待输入状态
        if self.state.is_waiting_for_input():
            await self._wait_for_input()
            continue
        
        # 检查是否需要停止
        if self.state.should_stop():
            # 处理停止逻辑
            continue
        
        # 处理 LLM 失败情况
        if self.state.llm_failed:
            await self._wait_for_input()
            continue
        
        # 增加迭代次数
        self.state.increment_iteration()
        
        # 检查是否接近最大迭代次数
        if self.state.is_approaching_max_iterations():
            # 发送警告消息
        
        try:
            # 处理单轮迭代
            should_finish = await self._process_iteration(tracer)
            if should_finish:
                # 处理完成逻辑
                continue
        except Exception as e:
            # 处理异常
            continue
```

### 7.2 工具执行算法

```python
async def _execute_actions(self, actions: list[Any], tracer: Optional["Tracer"]) -> bool:
    # 添加动作到状态
    for action in actions:
        self.state.add_action(action)
    
    # 创建工具执行任务
    tool_task = asyncio.create_task(
        process_tool_invocations(actions, conversation_history, self.state)
    )
    self._current_task = tool_task
    
    try:
        # 等待工具执行完成
        should_agent_finish = await tool_task
        self._current_task = None
    except asyncio.CancelledError:
        # 处理任务取消
        self._current_task = None
        self.state.add_error("Tool execution cancelled by user")
        raise
    
    # 更新对话历史
    self.state.messages = conversation_history
    
    # 返回是否应该结束
    if should_agent_finish:
        self.state.set_completed({"success": True})
        # 更新状态
        return True
    
    return False
```

## 8. 安全考虑

1. **容器隔离**: 使用 Docker 容器提供隔离的运行环境，防止恶意代码影响主机系统
2. **认证机制**: 工具服务器使用 Bearer 令牌进行认证，确保只有授权的 Agent 可以调用
3. **权限控制**: 容器运行时使用最小权限原则，只添加必要的权限（如 NET_ADMIN, NET_RAW）
4. **资源限制**: Docker 容器可以配置资源限制，防止资源耗尽攻击
5. **通信加密**: 虽然当前使用 HTTP，但可以扩展为 HTTPS 以加密通信

## 9. 总结与建议

### 9.1 系统优势

1. **模块化设计**: Agent 核心逻辑与 Docker 交互分离，便于扩展和维护
2. **隔离性强**: 使用 Docker 容器提供强隔离，提高系统安全性
3. **可扩展性好**: 支持多种工具和 LLM，便于扩展新功能
4. **状态管理完善**: 详细的状态记录，便于调试和监控
5. **错误处理机制**: 完善的错误处理和恢复机制，提高系统可靠性

### 9.2 改进建议

1. **使用 HTTPS**: 当前工具服务器使用 HTTP，建议改为 HTTPS 以提高通信安全性
2. **添加资源限制**: 为 Docker 容器添加资源限制（CPU、内存、磁盘），防止资源耗尽
3. **完善日志系统**: 增强日志记录，便于监控和审计
4. **添加监控指标**: 收集系统运行指标，便于性能分析和优化
5. **支持多种运行时**: 考虑支持其他容器运行时（如 Podman），提高系统兼容性

## 10. 参考文件

| 文件名                          | 路径                                  | 功能描述                          |
|--------------------------------|--------------------------------------|----------------------------------|
| base_agent.py                  | strix/agents/base_agent.py           | Agent 基类实现                   |
| state.py                       | strix/agents/state.py                | Agent 状态管理                   |
| strix_agent.py                 | strix/agents/StrixAgent/strix_agent.py | 具体 Agent 实现                 |
| docker_runtime.py              | strix/runtime/docker_runtime.py      | Docker 容器管理                  |
| runtime.py                     | strix/runtime/runtime.py             | 运行时接口定义                  |
| tool_server.py                 | strix/runtime/tool_server.py         | 工具服务器实现                  |
