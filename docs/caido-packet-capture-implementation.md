# Caido 抓包实现详细分析

## 1. 引言

Strix 项目集成了 Caido 作为其核心抓包分析工具，用于捕获、分析和修改网络流量。本文档详细介绍了 Caido 在 Strix 项目中的实现细节，包括安装配置、启动流程、Agent 交互机制等。

## 2. Caido 工具介绍

Caido 是一个现代化的网络安全工具，专为安全测试和流量分析设计，具有以下特点：

- 轻量级 CLI 设计
- GraphQL API 接口
- 强大的流量捕获和分析能力
- 支持作用域管理
- 自动生成站点地图
- 支持请求修改和重放

## 3. Docker 中的 Caido 安装与配置

### 3.1 Dockerfile 安装

Caido 在 Dockerfile 中通过以下步骤安装：

```bash
# 根据架构下载对应的 Caido CLI
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        CAIDO_ARCH="x86_64"; \
    elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        CAIDO_ARCH="aarch64"; \
    else \
        echo "Unsupported architecture: $ARCH" && exit 1; \
    fi && \
    wget -O caido-cli.tar.gz https://caido.download/releases/v0.48.0/caido-cli-v0.48.0-linux-${CAIDO_ARCH}.tar.gz && \
    tar -xzf caido-cli.tar.gz && \
    chmod +x caido-cli && \
    rm caido-cli.tar.gz && \
    mv caido-cli /usr/local/bin/
```

### 3.2 环境变量配置

Caido 相关的环境变量在容器中配置：

| 环境变量 | 用途 | 默认值 |
|---------|------|-------|
| CAIDO_PORT | Caido 服务监听端口 | 动态分配 |
| CAIDO_API_TOKEN | Caido API 认证令牌 | 自动生成 |
| http_proxy | HTTP 代理设置 | http://127.0.0.1:${CAIDO_PORT} |
| https_proxy | HTTPS 代理设置 | http://127.0.0.1:${CAIDO_PORT} |

## 4. Caido 服务启动流程

### 4.1 容器初始化脚本

Caido 在 `docker-entrypoint.sh` 脚本中启动，完整流程如下：

1. **检查端口配置**：确保 `CAIDO_PORT` 环境变量已设置
2. **启动 Caido 服务**：
   ```bash
   caido-cli --listen 127.0.0.1:${CAIDO_PORT} \
             --allow-guests \
             --no-logging \
             --no-open \
             --import-ca-cert /app/certs/ca.p12 \
             --import-ca-cert-pass "" > /dev/null 2>&1 &
   ```
3. **等待 API 就绪**：
   ```bash
   for i in {1..30}; do
     if curl -s -o /dev/null http://localhost:${CAIDO_PORT}/graphql; then
       echo "Caido API is ready."
       break
     fi
     sleep 1
   done
   ```
4. **获取 API 令牌**：
   ```bash
   TOKEN=$(curl -s -X POST \
     -H "Content-Type: application/json" \
     -d '{"query":"mutation LoginAsGuest { loginAsGuest { token { accessToken } } }"}' \
     http://localhost:${CAIDO_PORT}/graphql | jq -r '.data.loginAsGuest.token.accessToken')
   ```
5. **创建并选择项目**：
   ```bash
   # 创建项目
   CREATE_PROJECT_RESPONSE=$(curl -s -X POST \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $TOKEN" \
     -d '{"query":"mutation CreateProject { createProject(input: {name: \"sandbox\", temporary: true}) { project { id } } }"}' \
     http://localhost:${CAIDO_PORT}/graphql)
   
   # 选择项目
   SELECT_RESPONSE=$(curl -s -X POST \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $TOKEN" \
     -d '{"query":"mutation SelectProject { selectProject(id: \"'$PROJECT_ID'\") { currentProject { project { id } } } }"}' \
     http://localhost:${CAIDO_PORT}/graphql)
   ```
6. **配置系统级代理**：将所有流量通过 Caido 转发

### 4.2 系统级代理配置

容器初始化脚本会配置系统级代理，确保所有流量都通过 Caido 捕获：

```bash
# 配置环境变量
cat << EOF | sudo tee /etc/profile.d/proxy.sh
export http_proxy=http://127.0.0.1:${CAIDO_PORT}
export https_proxy=http://127.0.0.1:${CAIDO_PORT}
export HTTP_PROXY=http://127.0.0.1:${CAIDO_PORT}
export HTTPS_PROXY=http://127.0.0.1:${CAIDO_PORT}
export ALL_PROXY=http://127.0.0.1:${CAIDO_PORT}
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
export CAIDO_API_TOKEN=${TOKEN}
EOF

# 更新 wget 配置
cat << EOF | sudo tee /etc/wgetrc
use_proxy=yes
http_proxy=http://127.0.0.1:${CAIDO_PORT}
https_proxy=http://127.0.0.1:${CAIDO_PORT}
EOF
```

## 5. Agent 与 Caido 交互机制

### 5.1 代理工具架构

Agent 通过以下组件与 Caido 交互：

```
+----------------+     +----------------+     +----------------+
|   Agent 进程    | --> |  proxy_actions | --> | ProxyManager  |
+----------------+     +----------------+     +----------------+
                                                   |
                                                   v
                                           +----------------+
                                           |  Caido GraphQL |
                                           |      API       |
                                           +----------------+
```

### 5.2 核心交互组件

#### 5.2.1 ProxyManager 类

`ProxyManager` 类是 Agent 与 Caido 交互的核心，实现了：

- 与 Caido API 的连接初始化
- GraphQL 客户端管理
- Caido API 调用封装
- 响应数据处理

```python
class ProxyManager:
    def __init__(self, auth_token: str | None = None):
        host = "127.0.0.1"
        port = os.getenv("CAIDO_PORT", "56789")
        self.base_url = f"http://{host}:{port}/graphql"
        self.proxies = {"http": f"http://{host}:{port}", "https": f"http://{host}:{port}"}
        self.auth_token = auth_token or os.getenv("CAIDO_API_TOKEN")
        self.transport = RequestsHTTPTransport(
            url=self.base_url, headers={"Authorization": f"Bearer {self.auth_token}"}
        )
        self.client = Client(transport=self.transport, fetch_schema_from_transport=False)
```

#### 5.2.2 工具函数注册

代理工具通过装饰器注册：

```python
@register_tool
def list_requests(
    httpql_filter: str | None = None,
    start_page: int = 1,
    end_page: int = 1,
    page_size: int = 50,
    sort_by: Literal[...],
    sort_order: Literal["asc", "desc"] = "desc",
    scope_id: str | None = None,
) -> dict[str, Any]:
    manager = get_proxy_manager()
    return manager.list_requests(
        httpql_filter, start_page, end_page, page_size, sort_by, sort_order, scope_id
    )
```

## 6. 核心工具函数实现

### 6.1 请求列表查询

```python
def list_requests(
    self,
    httpql_filter: str | None = None,
    start_page: int = 1,
    end_page: int = 1,
    page_size: int = 50,
    sort_by: str = "timestamp",
    sort_order: str = "desc",
    scope_id: str | None = None,
) -> dict[str, Any]:
    # 计算分页参数
    offset = (start_page - 1) * page_size
    limit = (end_page - start_page + 1) * page_size
    
    # GraphQL 查询
    query = gql("""
        query GetRequests(
            $limit: Int, $offset: Int, $filter: HTTPQL,
            $order: RequestResponseOrderInput, $scopeId: ID
        ) {
            requestsByOffset(
                limit: $limit, offset: $offset, filter: $filter,
                order: $order, scopeId: $scopeId
            ) {
                edges {
                    node {
                        id method host path query createdAt length isTls port
                        source alteration fileExtension
                        response { id statusCode length roundtripTime createdAt }
                    }
                }
                count { value }
            }
        }
    """)
    
    # 执行查询并处理结果
    # ...
```

### 6.2 请求详情查看

```python
def view_request(
    self,
    request_id: str,
    part: str = "request",
    search_pattern: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    # 根据请求部分选择不同的查询
    queries = {
        "request": """query GetRequest($id: ID!) { ... }""",
        "response": """query GetRequest($id: ID!) { ... }""",
    }
    
    # 执行查询
    result = self.client.execute(gql(queries[part]), variable_values={"id": request_id})
    
    # 处理响应，解码 Base64 内容
    raw_content = request_data.get("raw")
    content = base64.b64decode(raw_content).decode("utf-8", errors="replace")
    
    # 搜索或分页处理
    if search_pattern:
        return self._search_content(request_data, content, search_pattern)
    else:
        return self._paginate_content(request_data, content, page, page_size)
```

### 6.3 请求发送与修改

```python
def send_simple_request(
    self,
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str = "",
    timeout: int = 30,
) -> dict[str, Any]:
    # 通过 Caido 代理发送请求
    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        data=body or None,
        proxies=self.proxies,
        timeout=timeout,
        verify=False,
    )
    
    # 处理响应
    # ...
```

## 7. 数据通信协议

### 7.1 通信方式

- **协议类型**：GraphQL
- **传输层**：HTTP
- **认证方式**：Bearer 令牌
- **通信端口**：动态分配（通过 `CAIDO_PORT` 环境变量）
- **数据格式**：JSON

### 7.2 认证机制

1. **令牌生成**：容器启动时通过 GraphQL mutation 获取
2. **令牌存储**：存储在 `CAIDO_API_TOKEN` 环境变量中
3. **请求认证**：通过 `Authorization` 请求头传递
   ```
   Authorization: Bearer <token>
   ```

## 8. 流量管理机制

### 8.1 流量捕获范围

Caido 作为系统级代理，捕获以下流量：

- Agent 发送的 HTTP/HTTPS 请求
- 工具执行过程中产生的网络流量
- 其他进程产生的网络流量
- 容器内所有出站流量

### 8.2 作用域管理

Agent 可以通过工具函数管理 Caido 的作用域规则：

```python
@register_tool
def scope_rules(
    action: Literal["get", "list", "create", "update", "delete"],
    allowlist: list[str] | None = None,
    denylist: list[str] | None = None,
    scope_id: str | None = None,
    scope_name: str | None = None,
) -> dict[str, Any]:
    manager = get_proxy_manager()
    return manager.scope_rules(action, allowlist, denylist, scope_id, scope_name)
```

## 9. Agent 分析流程

### 9.1 被动分析流程

1. **调用 `list_requests`**：获取捕获的请求列表
2. **筛选请求**：根据条件筛选感兴趣的请求
3. **调用 `view_request`**：查看请求详情
4. **分析内容**：分析请求/响应内容，识别潜在问题
5. **生成报告**：根据分析结果生成报告

### 9.2 主动分析流程

1. **调用 `send_request`**：发送新的 HTTP/HTTPS 请求
2. **获取响应**：获取并分析响应结果
3. **调用 `repeat_request`**：修改并重复请求
4. **比较结果**：比较不同请求的响应差异
5. **识别漏洞**：根据差异识别潜在漏洞

### 9.3 站点地图分析

1. **调用 `list_sitemap`**：获取站点地图
2. **浏览站点结构**：分析网站的 URL 结构
3. **调用 `view_sitemap_entry`**：查看具体条目详情
4. **分析请求模式**：分析不同路径的请求模式
5. **发现隐藏端点**：根据模式发现潜在的隐藏端点

## 10. 整体工作流程

```
+----------------+     +----------------+     +----------------+
|   容器启动      | --> |  Caido 初始化   | --> | 系统代理配置   |
+----------------+     +----------------+     +----------------+
        |                      |                      |
        v                      v                      v
+----------------+     +----------------+     +----------------+
|  Agent 启动     | --> | 代理工具注册   | --> | GraphQL 客户端  |
+----------------+     +----------------+     +----------------+
        |                      |                      |
        v                      v                      v
+----------------+     +----------------+     +----------------+
|  扫描任务执行   | --> | 代理工具调用   | --> | Caido API 调用  |
+----------------+     +----------------+     +----------------+
        |                      |                      |
        v                      v                      v
+----------------+     +----------------+     +----------------+
|  结果分析       | <-- | 响应数据处理   | <-- | 流量数据返回    |
+----------------+     +----------------+     +----------------+
        |
        v
+----------------+
|  生成扫描报告   |
+----------------+
```

## 11. 优势与特点

1. **集成化设计**：Caido 与 Agent 无缝集成，提供统一的安全测试平台
2. **全面的流量捕获**：作为系统级代理，捕获所有网络流量
3. **强大的分析能力**：提供多种工具函数，支持复杂的流量分析
4. **灵活的配置**：支持动态配置作用域规则
5. **直观的站点地图**：自动生成站点地图，便于分析网站结构
6. **安全的通信**：使用 Bearer 令牌认证，确保 API 安全
7. **异步执行**：代理工具支持异步执行，提高并发性能
8. **可扩展设计**：支持添加新的代理工具函数

## 12. 代码优化建议

### 12.1 错误处理增强

当前代码在处理 Caido API 错误时，可以进一步增强：

```python
# 当前实现
try:
    result = self.client.execute(query, variable_values=variables)
except (TransportQueryError, ValueError, KeyError) as e:
    return {"requests": [], "total_count": 0, "error": f"Error fetching requests: {e}"}

# 优化建议
try:
    result = self.client.execute(query, variable_values=variables)
except TransportQueryError as e:
    # 详细解析 GraphQL 错误
    error_details = []
    for error in e.errors:
        error_details.append({
            "message": error.get("message"),
            "locations": error.get("locations"),
            "path": error.get("path")
        })
    return {"requests": [], "total_count": 0, "error": "GraphQL query failed", "details": error_details}
except ValueError as e:
    return {"requests": [], "total_count": 0, "error": f"Invalid response format: {e}"}
except KeyError as e:
    return {"requests": [], "total_count": 0, "error": f"Missing expected field: {e}"}
```

### 12.2 缓存机制添加

为频繁调用的 API 添加缓存机制，减少重复请求：

```python
# 添加缓存装饰器
def cache_result(func):
    cache = {}
    
    def wrapper(*args, **kwargs):
        key = str(args) + str(kwargs)
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        return cache[key]
    
    return wrapper

# 应用到需要缓存的方法
@cache_result
def list_sitemap(self, ...):
    # 实现
```

### 12.3 批量操作支持

添加批量操作支持，提高处理大量请求的效率：

```python
def batch_send_requests(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # 批量发送请求，使用异步方式提高效率
    async def send_single(req):
        # 发送单个请求
        # ...
    
    # 使用 asyncio 并行发送请求
    results = await asyncio.gather(*[send_single(req) for req in requests])
    return results
```

## 13. 总结

Caido 作为 Strix 项目的核心抓包分析工具，提供了强大的流量捕获和分析能力。通过 Docker 容器化部署和系统级代理配置，Caido 能够捕获所有网络流量，并通过 GraphQL API 与 Agent 进行交互。

Agent 通过一系列代理工具函数，实现了对 Caido 捕获流量的查询、分析和修改，支持被动分析、主动测试和站点地图分析等多种场景。

这种设计提供了一个强大、灵活且安全的自动化安全扫描平台，能够有效地执行各种安全测试任务。通过不断优化和扩展，可以进一步增强 Caido 在 Strix 项目中的功能和性能。