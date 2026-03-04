# Docker 环境函数总结

本文档总结了 Strix 项目中所有与 Docker 环境相关的函数，包括函数名称、所在文件位置、功能描述和调用关系。

---

## 1. 鰭像管理函数

### 1.1 镜像名称定义

| 变量名 | 文件位置 | 说明 |
|--------|----------|------|
| `STRIX_IMAGE` | `strix/runtime/docker_runtime.py` L17 | Docker 镜像名称，默认值: `ghcr.io/usestrix/strix-sandbox:0.1.10`，可通过环境变量 `STRIX_IMAGE` 覆盖 |

```python
STRIX_IMAGE = os.getenv("STRIX_IMAGE", "ghcr.io/usestrix/strix-sandbox:0.1.10")
```

---

### 1.2 镜像检查与拉取函数

| 函数名 | 文件位置 | 功能描述 |
|--------|----------|----------|
| `check_docker_installed()` | `strix/interface/main.py` L159 | 检查 Docker 是否已安装 |
| `check_docker_connection()` | `strix/interface/utils.py` L487 | 连接 Docker daemon 并返回客户端 |
| `image_exists()` | `strix/interface/utils.py` L512 | 检查指定镜像是否存在于本地 |
| `pull_docker_image()` | `strix/interface/main.py` L419 | 拉取 Docker 镜像（如果不存在） |
| `_verify_image_available()` | `strix/runtime/docker_runtime.py` L55 | 验证镜像可用性（带重试机制） |

#### 详细说明

##### check_docker_installed()
```python
# strix/interface/main.py L159
def check_docker_installed() -> None:
    """检查 Docker 是否已安装在系统中"""
    if shutil.which("docker") is None:
        # 打印错误信息并退出
        sys.exit(1)
```

##### check_docker_connection()
```python
# strix/interface/utils.py L487
def check_docker_connection() -> Any:
    """连接本地 Docker daemon 并返回客户端对象"""
    try:
        return docker.from_env()  # 使用环境变量配置连接 Docker
    except DockerException:
        # 打印错误面板并抛出异常
        raise RuntimeError("Docker not available")
```

##### image_exists()
```python
# strix/interface/utils.py L512
def image_exists(client: Any, image_name: str) -> bool:
    """检查指定镜像是否存在于本地 Docker 环境"""
    try:
        client.images.get(image_name)  # 调用 Docker API
    except ImageNotFound:
        return False
    else:
        return True
```

##### pull_docker_image()
```python
# strix/interface/main.py L419
def pull_docker_image() -> None:
    """拉取 Docker 镜像（仅在镜像不存在时执行）"""
    client = check_docker_connection()
    
    if image_exists(client, STRIX_IMAGE):
        return  # 镜像已存在，跳过拉取
    
    # 流式拉取镜像并显示进度
    for line in client.api.pull(STRIX_IMAGE, stream=True, decode=True):
        process_pull_line(line, layers_info, status, last_update)
```

##### _verify_image_available()
```python
# strix/runtime/docker_runtime.py L55
def _verify_image_available(self, image_name: str, max_retries: int = 3) -> None:
    """验证镜像可用性，支持重试机制"""
    for attempt in range(max_retries):
        try:
            image = self.client.images.get(image_name)
            # 验证镜像元数据完整性
            if not image.id or not image.attrs:
                raise ImageNotFound(f"Image {image_name} metadata incomplete")
        except ImageNotFound:
            if attempt == max_retries - 1:
                raise
            time.sleep(2**attempt)  # 指数退避
```

---

## 2. 容器管理函数

### 2.1 容器创建与管理

| 函数名 | 文件位置 | 功能描述 |
|--------|----------|----------|
| `_generate_sandbox_token()` | `strix/runtime/docker_runtime.py` L33 | 生成沙箱安全令牌 |
| `_find_available_port()` | `strix/runtime/docker_runtime.py` L36 | 查找可用端口 |
| `_get_scan_id()` | `strix/runtime/docker_runtime.py` L41 | 获取扫描任务 ID |
| `_create_container_with_retry()` | `strix/runtime/docker_runtime.py` L80 | 创建容器（带重试机制） |
| `_get_or_create_scan_container()` | `strix/runtime/docker_runtime.py` L154 | 获取或创建扫描容器 |
| `_initialize_container()` | `strix/runtime/docker_runtime.py` L226 | 初始化容器环境 |
| `_copy_local_directory_to_container()` | `strix/runtime/docker_runtime.py` L253 | 复制本地目录到容器 |

#### 详细说明

##### _generate_sandbox_token()
```python
# strix/runtime/docker_runtime.py L33
def _generate_sandbox_token(self) -> str:
    """生成用于工具服务器认证的安全令牌"""
    return secrets.token_urlsafe(32)
```

##### _find_available_port()
```python
# strix/runtime/docker_runtime.py L36
def _find_available_port(self) -> int:
    """查找本地可用端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]
```

##### _create_container_with_retry()
```python
# strix/runtime/docker_runtime.py L80
def _create_container_with_retry(self, scan_id: str, max_retries: int = 3) -> Container:
    """创建 Docker 容器，支持重试机制"""
    for attempt in range(max_retries):
        try:
            self._verify_image_available(STRIX_IMAGE)
            
            container = self.client.containers.run(
                STRIX_IMAGE,
                command="sleep infinity",
                detach=True,
                ports={...},
                cap_add=["NET_ADMIN", "NET_RAW"],
                environment={...},
            )
            
            self._initialize_container(container, ...)
            return container
        except DockerException:
            time.sleep((2**attempt) + (0.1 * attempt))
```

##### _get_or_create_scan_container()
```python
# strix/runtime/docker_runtime.py L154
def _get_or_create_scan_container(self, scan_id: str) -> Container:
    """获取现有容器或创建新容器"""
    # 1. 检查内存中的容器引用
    if self._scan_container:
        return self._scan_container
    
    # 2. 按名称查找容器
    container = self.client.containers.get(container_name)
    
    # 3. 按标签查找容器
    containers = self.client.containers.list(
        all=True, filters={"label": f"strix-scan-id={scan_id}"}
    )
    
    # 4. 创建新容器
    return self._create_container_with_retry(scan_id)
```

##### _initialize_container()
```python
# strix/runtime/docker_runtime.py L226
def _initialize_container(
    self, container: Container, caido_port: int, tool_server_port: int, tool_server_token: str
) -> None:
    """初始化容器内的服务"""
    # 1. 启动 Caido 代理
    container.exec_run(
        f"bash -c 'export CAIDO_PORT={caido_port} && /usr/local/bin/docker-entrypoint.sh true'"
    )
    
    # 2. 获取 Caido API Token
    result = container.exec_run("bash -c 'source /etc/profile.d/proxy.sh && echo $CAIDO_API_TOKEN'")
    
    # 3. 启动工具服务器
    container.exec_run(
        f"STRIX_SANDBOX_MODE=true CAIDO_API_TOKEN={caido_token} "
        f"poetry run python strix/runtime/tool_server.py --token {tool_server_token}"
    )
```

##### _copy_local_directory_to_container()
```python
# strix/runtime/docker_runtime.py L253
def _copy_local_directory_to_container(
    self, container: Container, local_path: str, target_name: str | None = None
) -> None:
    """将本地目录复制到容器的 /workspace 目录"""
    # 1. 创建 tar 归档
    tar_buffer = BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        for item in local_path_obj.rglob("*"):
            tar.add(item, arcname=...)
    
    # 2. 传输到容器
    container.put_archive("/workspace", tar_buffer.getvalue())
    
    # 3. 修改权限
    container.exec_run("chown -R pentester:pentester /workspace", user="root")
```

---

## 3. 沙箱生命周期管理

### 3.1 沙箱创建与销毁

| 函数名 | 文件位置 | 功能描述 |
|--------|----------|----------|
| `create_sandbox()` | `strix/runtime/docker_runtime.py` L294 | 创建沙箱环境（异步） |
| `get_sandbox_url()` | `strix/runtime/docker_runtime.py` L356 | 获取沙箱 API 地址 |
| `destroy_sandbox()` | `strix/runtime/docker_runtime.py` L384 | 销毁沙箱容器 |
| `_resolve_docker_host()` | `strix/runtime/docker_runtime.py` L370 | 解析 Docker 主机地址 |
| `_register_agent_with_tool_server()` | `strix/runtime/docker_runtime.py` L338 | 注册 Agent 到工具服务器 |

#### 详细说明

##### create_sandbox()
```python
# strix/runtime/docker_runtime.py L294
async def create_sandbox(
    self,
    agent_id: str,
    existing_token: str | None = None,
    local_sources: list[dict[str, str]] | None = None,
) -> SandboxInfo:
    """创建沙箱环境"""
    scan_id = self._get_scan_id(agent_id)
    container = self._get_or_create_scan_container(scan_id)
    
    # 复制本地源代码
    for source in local_sources or []:
        self._copy_local_directory_to_container(container, source["path"], source.get("name"))
    
    # 注册 Agent
    await self._register_agent_with_tool_server(api_url, agent_id, token)
    
    return {
        "workspace_id": container_id,
        "api_url": api_url,
        "auth_token": token,
        "tool_server_port": self._tool_server_port,
        "agent_id": agent_id,
    }
```

##### get_sandbox_url()
```python
# strix/runtime/docker_runtime.py L356
async def get_sandbox_url(self, container_id: str, port: int) -> str:
    """获取沙箱的 API 地址"""
    container = self.client.containers.get(container_id)
    host = self._resolve_docker_host()
    return f"http://{host}:{port}"
```

##### destroy_sandbox()
```python
# strix/runtime/docker_runtime.py L384
async def destroy_sandbox(self, container_id: str) -> None:
    """销毁沙箱容器"""
    try:
        container = self.client.containers.get(container_id)
        container.remove(force=True)
    except NotFound:
        pass  # 容器已不存在
```

##### _resolve_docker_host()
```python
# strix/runtime/docker_runtime.py L370
def _resolve_docker_host(self) -> str:
    """解析 Docker 主机地址"""
    docker_host = os.getenv("DOCKER_HOST", "")
    if not docker_host:
        return "127.0.0.1"
    # 解析 DOCKER_HOST URL
    return parsed_host
```

---

## 4. Agent 沙箱初始化

| 函数名 | 文件位置 | 功能描述 |
|--------|----------|----------|
| `_initialize_sandbox_and_state()` | `strix/agents/base_agent.py` L330 | Agent 初始化时创建沙箱 |

```python
# strix/agents/base_agent.py L330
async def _initialize_sandbox_and_state(self, task: str) -> None:
    """初始化沙箱环境和 Agent 状态"""
    sandbox_mode = os.getenv("STRIX_SANDBOX_MODE", "false").lower() == "true"
    
    if not sandbox_mode and self.state.sandbox_id is None:
        runtime = get_runtime()
        sandbox_info = await runtime.create_sandbox(
            self.state.agent_id, 
            self.state.sandbox_token, 
            self.local_sources
        )
        self.state.sandbox_id = sandbox_info["workspace_id"]
        self.state.sandbox_token = sandbox_info["auth_token"]
```

---

## 5. 抽象运行时接口

| 类名 | 文件位置 | 功能描述 |
|------|----------|----------|
| `AbstractRuntime` | `strix/runtime/runtime.py` L13 | 运行时抽象基类 |
| `SandboxInfo` | `strix/runtime/runtime.py` L5 | 沙箱信息类型定义 |

```python
# strix/runtime/runtime.py

class SandboxInfo(TypedDict):
    workspace_id: str
    api_url: str
    auth_token: str | None
    tool_server_port: int
    agent_id: str


class AbstractRuntime(ABC):
    @abstractmethod
    async def create_sandbox(self, agent_id: str, ...) -> SandboxInfo:
        raise NotImplementedError
    
    @abstractmethod
    async def get_sandbox_url(self, container_id: str, port: int) -> str:
        raise NotImplementedError
    
    @abstractmethod
    async def destroy_sandbox(self, container_id: str) -> None:
        raise NotImplementedError
```

---

## 6. 辅助函数

### 6.1 镜像拉取进度处理

| 函数名 | 文件位置 | 功能描述 |
|--------|----------|----------|
| `update_layer_status()` | `strix/interface/utils.py` L521 | 更新镜像层状态图标 |
| `process_pull_line()` | `strix/interface/utils.py` L534 | 处理拉取进度输出 |

```python
# strix/interface/utils.py L521
def update_layer_status(layers_info: dict[str, str], layer_id: str, layer_status: str) -> None:
    """根据拉取状态更新图标"""
    if "Pull complete" in layer_status or "Already exists" in layer_status:
        layers_info[layer_id] = "✓"
    elif "Downloading" in layer_status:
        layers_info[layer_id] = "↓"
    elif "Extracting" in layer_status:
        layers_info[layer_id] = "📦"
    elif "Waiting" in layer_status:
        layers_info[layer_id] = "⏳"
```

---

## 7. 函数调用关系图

```
程序启动 (main.py)
    │
    ├── check_docker_installed()          # 检查 Docker 安装
    │
    ├── pull_docker_image()               # 拉取镜像
    │       ├── check_docker_connection() # 连接 Docker
    │       ├── image_exists()            # 检查镜像
    │       └── client.api.pull()         # 拉取镜像
    │
    └── Agent 启动
            │
            └── _initialize_sandbox_and_state()
                    │
                    └── runtime.create_sandbox()
                            │
                            ├── _get_or_create_scan_container()
                            │       ├── _verify_image_available()
                            │       └── _create_container_with_retry()
                            │               └── _initialize_container()
                            │
                            ├── _copy_local_directory_to_container()
                            │
                            └── _register_agent_with_tool_server()
```

---

## 8. 文件位置汇总

| 文件路径 | 包含的函数 |
|----------|-----------|
| `strix/interface/main.py` | `check_docker_installed()`, `pull_docker_image()` |
| `strix/interface/utils.py` | `check_docker_connection()`, `image_exists()`, `update_layer_status()`, `process_pull_line()` |
| `strix/runtime/docker_runtime.py` | `_generate_sandbox_token()`, `_find_available_port()`, `_get_scan_id()`, `_verify_image_available()`, `_create_container_with_retry()`, `_get_or_create_scan_container()`, `_initialize_container()`, `_copy_local_directory_to_container()`, `create_sandbox()`, `get_sandbox_url()`, `destroy_sandbox()`, `_resolve_docker_host()`, `_register_agent_with_tool_server()` |
| `strix/runtime/runtime.py` | `AbstractRuntime` (抽象基类), `SandboxInfo` (类型定义) |
| `strix/agents/base_agent.py` | `_initialize_sandbox_and_state()` |

---

## 9. 环境变量

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `STRIX_IMAGE` | Docker 镜像名称 | `ghcr.io/usestrix/strix-sandbox:0.1.10` |
| `STRIX_SANDBOX_MODE` | 沙箱模式（容器内运行时设为 true） | `false` |
| `DOCKER_HOST` | Docker daemon 地址 | 本地 socket |

---

## 10. 总结

Strix 的 Docker 环境管理采用分层架构：

1. **接口层** (`interface/`): 负责 Docker 安装检查、镜像拉取、用户交互
2. **运行时层** (`runtime/`): 负责容器生命周期管理、沙箱创建与销毁
3. **Agent 层** (`agents/`): 在初始化时调用运行时创建沙箱

核心流程：
```
启动 → 检查Docker → 拉取镜像 → 创建容器 → 初始化服务 → Agent使用沙箱 → 销毁容器
```
