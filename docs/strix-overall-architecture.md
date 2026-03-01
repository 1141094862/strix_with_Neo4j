# Strix 项目整体架构与核心实现

## 1. 项目概述

Strix 是一个基于代理（Agent）的自动化安全扫描系统，通过 Docker 容器提供隔离的运行环境，实现安全扫描任务的执行。本文档将全面梳理 Strix 项目的整体架构、核心流程和实现细节，结合之前的两个文档（Docker 镜像工具与设置、Agent 逻辑结构与 Docker 环境交互）以及相关代码，提供一个完整的项目视图。

## 2. 系统架构

### 2.1 整体架构图

```
+-------------------+
|   客户端界面       |
|  (CLI/TUI/API)    |
+-------------------+
        |
        v
+-------------------+
|   主控制进程       |
|  (strix-cli)      |
+-------------------+
        |
        | 1. 初始化配置
        v
+-------------------+
|   Agent 管理器     |
|  (BaseAgent)      |
+-------------------+
        |
        | 2. 创建沙箱
        v
+-------------------+
|   DockerRuntime   |
|  (容器管理)        |
+-------------------+
        |
        | 3. 启动容器
        v
+-------------------+
|   Docker 容器      |
|  (strix-sandbox)  |
+-------------------+
        |
        | 4. 初始化容器
        v
+-------------------+
|   Caido 代理       |
|  (网络流量拦截)    |
+-------------------+
        |
        | 5. 启动工具服务器
        v
+-------------------+
|   Tool Server     |
|  (工具执行服务)    |
+-------------------+
        |
        | 6. 注册 Agent
        v
+-------------------+
|   Agent 进程       |
|  (执行扫描任务)    |
+-------------------+
        |
        | 7. 执行工具
        v
+-------------------+
|   安全工具集       |
|  (nmap/sqlmap等)   |
+-------------------+
```

### 2.2 核心组件关系

| 组件名称 | 主要职责 | 关键文件 |
|---------|---------|---------|
| 主控制进程 | 启动和管理扫描任务 | strix/interface/cli.py, strix/interface/main.py |
| Agent 管理器 | 管理 Agent 生命周期 | strix/agents/base_agent.py |
| DockerRuntime | 管理 Docker 容器 | strix/runtime/docker_runtime.py |
| Tool Server | 处理工具调用请求 | strix/runtime/tool_server.py |
| Caido 代理 | 拦截和分析网络流量 | 容器内运行 |
| 安全工具集 | 执行各种安全扫描 | 容器内安装 |

## 3. 核心流程梳理

### 3.1 系统启动流程

1. **用户启动扫描**：
   - 用户通过 CLI/TUI 界面发起扫描请求
   - 主控制进程解析配置，初始化环境

2. **Agent 初始化**：
   - 创建 StrixAgent 实例
   - 初始化 LLM 客户端
   - 创建 AgentState 记录状态

3. **沙箱创建**：
   - Agent 调用 DockerRuntime.create_sandbox()
   - DockerRuntime 检查是否存在现有容器
   - 不存在则创建新的 Docker 容器
   - 复制本地资源到容器

4. **容器初始化**：
   - 启动 Caido 代理服务
   - 配置系统级代理
   - 启动工具服务器
   - 初始化证书信任

5. **Agent 注册**：
   - Agent 调用 Tool Server 的 /register_agent 接口
   - Tool Server 为 Agent 创建独立进程

### 3.2 扫描执行流程

1. **任务分配**：
   - 用户通过界面向 Agent 分配扫描任务
   - Agent 将任务添加到状态中

2. **LLM 交互**：
   - Agent 调用 LLM.generate() 生成响应
   - LLM 分析任务，生成工具调用指令

3. **工具执行**：
   - Agent 处理 LLM 生成的工具调用
   - 调用 Tool Server 的 /execute 接口
   - Tool Server 执行对应的安全工具
   - 返回执行结果给 Agent

4. **结果处理**：
   - Agent 分析工具执行结果
   - 将结果添加到对话历史
   - 决定下一步行动（继续扫描或结束）

5. **扫描结束**：
   - Agent 调用 finish_scan 工具结束扫描
   - 生成扫描报告
   - 清理资源

### 3.3 工具调用流程

1. **工具调用生成**：
   - LLM 基于任务和上下文生成工具调用
   - Agent 解析工具调用指令

2. **请求发送**：
   - Agent 构建工具调用请求
   - 发送 HTTP 请求到 Tool Server
   - 包含工具名称、参数和认证令牌

3. **请求验证**：
   - Tool Server 验证请求的合法性
   - 检查认证令牌
   - 确保 Agent 已注册

4. **工具执行**：
   - Tool Server 将请求放入 Agent 对应的队列
   - Agent 进程从队列中获取请求
   - 执行对应的工具函数
   - 转换参数格式
   - 调用实际工具

5. **结果返回**：
   - 工具执行结果放入响应队列
   - Tool Server 返回 JSON 响应给 Agent
   - Agent 处理响应结果

## 4. 核心实现部分

### 4.1 Agent 系统

#### 4.1.1 Agent 基类设计

**文件路径**: `strix/agents/base_agent.py`

BaseAgent 是所有 Agent 的基类，定义了 Agent 的核心逻辑和生命周期管理：

```python
class BaseAgent(metaclass=AgentMeta):
    max_iterations = 300
    agent_name: str = ""
    jinja_env: Environment
    default_llm_config: LLMConfig | None = None
    
    def __init__(self, config: dict[str, Any]):
        # 初始化配置、LLM客户端、状态等
    
    async def agent_loop(self, task: str) -> dict[str, Any]:
        # Agent 主循环
    
    async def _process_iteration(self, tracer: Optional["Tracer"]) -> bool:
        # 处理单轮迭代
    
    async def _execute_actions(self, actions: list[Any], tracer: Optional["Tracer"]) -> bool:
        # 执行工具调用
```

#### 4.1.2 Agent 状态管理

**文件路径**: `strix/agents/state.py`

AgentState 管理 Agent 的状态信息，包括：

```python
class AgentState(BaseModel):
    agent_id: str = Field(default_factory=_generate_agent_id)
    agent_name: str = "Strix Agent"
    parent_id: str | None = None
    sandbox_id: str | None = None
    sandbox_token: str | None = None
    sandbox_info: dict[str, Any] | None = None
    
    task: str = ""
    iteration: int = 0
    max_iterations: int = 300
    completed: bool = False
    stop_requested: bool = False
    waiting_for_input: bool = False
    llm_failed: bool = False
    
    messages: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    
    actions_taken: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)
    
    errors: list[str] = Field(default_factory=list)
```

### 4.2 Docker 运行时

#### 4.2.1 Docker 容器管理

**文件路径**: `strix/runtime/docker_runtime.py`

DockerRuntime 负责管理 Docker 容器的生命周期：

```python
class DockerRuntime(AbstractRuntime):
    def __init__(self) -> None:
        # 初始化 Docker 客户端
    
    async def create_sandbox(
        self, agent_id: str, existing_token: str | None = None, local_sources: list[dict[str, str]] | None = None
    ) -> SandboxInfo:
        # 创建或获取扫描容器
    
    def _get_or_create_scan_container(self, scan_id: str) -> Container:
        # 获取或创建容器
    
    def _initialize_container(
        self, container: Container, caido_port: int, tool_server_port: int, tool_server_token: str
    ) -> None:
        # 初始化容器
    
    async def destroy_sandbox(self, container_id: str) -> None:
        # 销毁容器
```

#### 4.2.2 工具服务器

**文件路径**: `strix/runtime/tool_server.py`

Tool Server 是运行在 Docker 容器内的 HTTP 服务器，负责处理工具调用请求：

```python
@app.post("/execute", response_model=ToolExecutionResponse)
async def execute_tool(
    request: ToolExecutionRequest, credentials: HTTPAuthorizationCredentials = security_dependency
) -> ToolExecutionResponse:
    # 验证令牌
    # 确保 Agent 进程存在
    # 发送工具执行请求到队列
    # 等待执行结果
    # 返回结果

@app.post("/register_agent")
async def register_agent(
    agent_id: str, credentials: HTTPAuthorizationCredentials = security_dependency
) -> dict[str, str]:
    # 验证令牌
    # 确保 Agent 进程存在
    # 返回注册状态
```

### 4.3 容器初始化脚本

**文件路径**: `containers/docker-entrypoint.sh`

容器启动时执行的初始化脚本，负责配置 Caido 代理和系统设置：

```bash
#!/bin/bash
set -e

# 检查 CAIDO_PORT 环境变量

# 启动 Caido 代理服务

# 等待 Caido API 就绪

# 获取 Caido API 令牌

# 创建和选择 Caido 项目

# 配置系统级代理设置

# 将 CA 证书添加到浏览器信任存储

# 完成初始化
```

## 5. 核心功能模块

### 5.1 Agent 系统

#### 5.1.1 初始化与配置

- **功能**: 初始化 Agent 实例，加载配置，设置 LLM 客户端，创建 Agent 状态
- **关键代码**: `BaseAgent.__init__()`, `_initialize_sandbox_and_state()`
- **配置参数**: LLM 配置、最大迭代次数、本地资源等

#### 5.1.2 主循环

- **功能**: Agent 的主循环，处理整个生命周期
- **流程**: 检查消息 → 处理等待状态 → 检查停止条件 → 增加迭代次数 → 调用 LLM → 执行工具 → 处理结果
- **关键代码**: `agent_loop()`

#### 5.1.3 LLM 交互

- **功能**: 与 LLM 进行交互，生成响应和工具调用
- **关键代码**: `_process_iteration()`
- **协议**: 使用对话历史格式，支持工具调用

#### 5.1.4 工具执行

- **功能**: 执行 LLM 生成的工具调用
- **关键代码**: `_execute_actions()`
- **机制**: 通过 Tool Server 执行工具，返回结果

### 5.2 Docker 容器系统

#### 5.2.1 容器管理

- **功能**: 管理 Docker 容器的生命周期
- **关键代码**: `DockerRuntime` 类的方法
- **操作**: 创建、获取、初始化、销毁容器

#### 5.2.2 代理配置

- **功能**: 配置系统级代理，所有网络请求通过 Caido 代理转发
- **配置文件**: `/etc/profile.d/proxy.sh`, `/etc/environment`, `/etc/wgetrc`
- **代理类型**: HTTP, HTTPS, ALL

#### 5.2.3 证书管理

- **功能**: 生成和管理自签名 CA 证书
- **证书位置**: `/app/certs/`
- **信任配置**: 系统信任存储和浏览器信任存储

### 5.3 工具系统

#### 5.3.1 工具注册与发现

- **功能**: 管理可用的工具，支持动态注册和发现
- **关键代码**: `strix/tools/registry.py`
- **机制**: 基于装饰器的工具注册，支持类型转换

#### 5.3.2 工具执行机制

- **功能**: 执行各种安全工具，处理参数和结果
- **关键代码**: `strix/tools/executor.py`
- **支持的工具**: nmap, sqlmap, nuclei, subfinder, naabu, ffuf 等

#### 5.3.3 工具分类

- **网络扫描工具**: nmap, naabu, httpx
- **漏洞检测工具**: sqlmap, nuclei, vulnx, zaproxy
- **Web 测试工具**: ffuf, dirsearch, arjun
- **代码分析工具**: semgrep, bandit, eslint
- **JavaScript 工具**: retire, JS-Snooper, jsniper.sh
- **JWT 工具**: jwt_tool

## 6. 数据流与通信

### 6.1 内部数据流

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

### 6.2 外部通信

1. **主进程与 Docker 通信**：
   - 使用 Docker SDK for Python
   - 执行容器管理操作
   - 监控容器状态

2. **Agent 与 Tool Server 通信**：
   - 使用 HTTP/REST API
   - Bearer 令牌认证
   - 异步通信模式

3. **Tool Server 与工具通信**：
   - 子进程方式执行工具
   - 队列通信机制
   - 同步执行模式

4. **容器与外部服务通信**：
   - 通过 Caido 代理转发
   - 支持 HTTP/HTTPS 协议
   - 可配置代理设置

## 7. 配置与部署

### 7.1 环境变量

| 环境变量 | 默认值 | 用途 |
|---------|---------|------|
| STRIX_SANDBOX_MODE | false | 沙箱模式开关 |
| STRIX_IMAGE | ghcr.io/usestrix/strix-sandbox:0.1.10 | Docker 镜像名称 |
| CAIDO_PORT | 动态分配 | Caido 代理端口 |
| TOOL_SERVER_PORT | 动态分配 | 工具服务器端口 |
| TOOL_SERVER_TOKEN | 随机生成 | 工具服务器认证令牌 |
| DOCKER_HOST |  | Docker 主机地址 |

### 7.2 部署方式

1. **本地部署**：
   - 安装 Docker 和 Python 环境
   - 克隆代码仓库
   - 安装依赖
   - 运行 strix-cli

2. **容器部署**：
   - 使用预构建的 Docker 镜像
   - 挂载必要的卷
   - 配置环境变量
   - 运行容器

3. **分布式部署**：
   - 主控制进程运行在一台服务器
   - Docker 容器运行在多台服务器
   - 通过网络通信

## 8. 安全设计

### 8.1 容器隔离

- **机制**: 使用 Docker 容器提供隔离环境
- **好处**: 防止恶意代码影响主机系统
- **配置**: 最小权限原则，只添加必要的权限

### 8.2 认证与授权

- **机制**: Bearer 令牌认证
- **应用**: 工具服务器 API 保护
- **生成**: 随机生成的强令牌

### 8.3 网络安全

- **机制**: Caido 代理拦截所有网络请求
- **好处**: 监控和分析网络流量
- **配置**: 系统级代理设置

### 8.4 数据安全

- **机制**: 本地存储扫描结果
- **好处**: 防止敏感数据泄露
- **配置**: 可配置输出目录

## 9. 核心算法与逻辑

### 9.1 Agent 主循环算法

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

### 9.2 工具执行算法

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

## 10. 项目优势与特点

1. **模块化设计**: Agent 核心逻辑与 Docker 交互分离，便于扩展和维护
2. **隔离性强**: 使用 Docker 容器提供强隔离，提高系统安全性
3. **可扩展性好**: 支持多种工具和 LLM，便于扩展新功能
4. **自动化程度高**: 从容器创建到扫描结束，全程自动化
5. **状态管理完善**: 详细的状态记录，便于调试和监控
6. **错误处理机制**: 完善的错误处理和恢复机制，提高系统可靠性
7. **全面的工具集**: 包含各种安全测试工具，满足不同场景需求
8. **灵活的配置**: 支持多种配置方式，适应不同环境

## 11. 改进建议

1. **使用 HTTPS**: 当前工具服务器使用 HTTP，建议改为 HTTPS 以提高通信安全性
2. **添加资源限制**: 为 Docker 容器添加资源限制（CPU、内存、磁盘），防止资源耗尽
3. **完善日志系统**: 增强日志记录，便于监控和审计
4. **添加监控指标**: 收集系统运行指标，便于性能分析和优化
5. **支持多种运行时**: 考虑支持其他容器运行时（如 Podman），提高系统兼容性
6. **增强可视化**: 提供更丰富的可视化界面，便于查看扫描进度和结果
7. **支持插件机制**: 允许用户自定义和扩展工具集
8. **优化性能**: 提高工具执行效率，减少扫描时间

## 12. 总结

Strix 项目是一个功能全面、设计良好的自动化安全扫描系统，结合了 Agent 技术、Docker 容器和各种安全工具，提供了一个强大的安全扫描平台。本文档全面梳理了 Strix 项目的整体架构、核心流程和实现细节，希望能够帮助读者更好地理解和使用该项目。

Strix 项目具有良好的模块化设计和扩展性，可以根据需要进行定制和扩展，适应不同的安全扫描场景。通过持续改进和优化，Strix 有望成为一个领先的自动化安全扫描工具，为安全团队提供强大的支持。