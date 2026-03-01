# Caido 抓包数据处理详细分析

## 1. 引言

在 Strix 项目中，Caido 作为核心抓包工具，负责捕获、存储和分析网络流量。本文档详细介绍了 Strix 如何处理 Caido 抓包获得的数据，包括数据获取、转换、过滤、搜索、分页和展示等核心实现。

## 2. 数据处理架构

### 2.1 整体架构

```
+----------------+     +----------------+     +----------------+
|  Caido API     | --> | ProxyManager   | --> | 工具函数包装   |
+----------------+     +----------------+     +----------------+
        ^                      |                      |
        |                      v                      v
+----------------+     +----------------+     +----------------+
|  Caido 存储    | <-- | 数据处理逻辑   | <-- | Agent 调用     |
+----------------+     +----------------+     +----------------+
```

### 2.2 核心组件

- **Caido API**：提供 GraphQL 接口，用于查询和操作抓包数据
- **ProxyManager**：封装与 Caido API 的交互，实现数据处理逻辑
- **工具函数包装**：将数据处理方法注册为 Agent 可调用的工具
- **Caido 存储**：Caido 内部的数据存储，保存捕获的网络流量

## 3. 核心数据结构

### 3.1 请求数据结构

```python
{
    "id": "request_id",
    "method": "GET",
    "host": "example.com",
    "path": "/api/v1/users",
    "query": "page=1&limit=10",
    "createdAt": "2023-01-01T00:00:00Z",
    "length": 123,
    "isTls": True,
    "port": 443,
    "source": "manual",
    "alteration": "none",
    "fileExtension": "json",
    "response": {
        "id": "response_id",
        "statusCode": 200,
        "length": 456,
        "roundtripTime": 123,
        "createdAt": "2023-01-01T00:00:00Z"
    }
}
```

### 3.2 响应数据结构

```python
{
    "id": "response_id",
    "statusCode": 200,
    "length": 456,
    "roundtripTime": 123,
    "createdAt": "2023-01-01T00:00:00Z",
    "raw": "base64_encoded_content"
}
```

### 3.3 站点地图数据结构

```python
{
    "id": "sitemap_id",
    "kind": "domain",
    "label": "example.com",
    "hasDescendants": True,
    "metadata": {
        "isTls": True,
        "port": 443
    },
    "request": {
        "method": "GET",
        "path": "/",
        "response": {
            "statusCode": 200
        }
    }
}
```

## 4. 数据获取机制

### 4.1 GraphQL 查询构建

ProxyManager 使用 GraphQL 查询从 Caido API 获取数据：

```python
def list_requests(self, ...):
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
    
    # 执行查询
    result = self.client.execute(query, variable_values=variables)
```

### 4.2 分页参数计算

```python
offset = (start_page - 1) * page_size
limit = (end_page - start_page + 1) * page_size
```

### 4.3 结果处理

```python
nodes = [edge["node"] for edge in data.get("edges", [])]
count_data = data.get("count") or {}

return {
    "requests": nodes,
    "total_count": count_data.get("value", 0),
    "start_page": start_page,
    "end_page": end_page,
    "page_size": page_size,
    "offset": offset,
    "returned_count": len(nodes),
    "sort_by": sort_by,
    "sort_order": sort_order,
}
```

## 5. 数据处理流程

### 5.1 请求详情处理流程

```
+----------------+     +----------------+     +----------------+
|  获取请求ID     | --> | GraphQL 查询   | --> | 响应解析       |
+----------------+     +----------------+     +----------------+
        |                      |                      |
        v                      v                      v
+----------------+     +----------------+     +----------------+
| Base64 解码    | --> | 内容搜索/分页  | --> | 结果格式化     |
+----------------+     +----------------+     +----------------+
        |                      |                      |
        v                      v                      v
+----------------+     +----------------+     +----------------+
| 返回处理结果   | <-- | 数据转换       | <-- | 数据验证       |
+----------------+     +----------------+     +----------------+
```

### 5.2 内容搜索流程

```python
def _search_content(self, request_data: dict[str, Any], content: str, pattern: str) -> dict[str, Any]:
    try:
        # 编译正则表达式
        regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        matches = []
        
        # 查找所有匹配
        for match in regex.finditer(content):
            start, end = match.start(), match.end()
            context_size = 120
            
            # 获取匹配上下文
            before = re.sub(r"\s+", " ", content[max(0, start - context_size) : start].strip())[-100:]
            after = re.sub(r"\s+", " ", content[end : end + context_size].strip())[:100]
            
            # 添加匹配结果
            matches.append({
                "match": match.group(),
                "before": before,
                "after": after,
                "position": start
            })
            
            # 限制匹配数量
            if len(matches) >= 20:
                break
        
        # 返回搜索结果
        return {
            "id": request_data.get("id"),
            "matches": matches,
            "total_matches": len(matches),
            "search_pattern": pattern,
            "truncated": len(matches) >= 20,
        }
    except re.error as e:
        return {"error": f"Invalid regex: {e}"}
```

### 5.3 内容分页流程

```python
def _paginate_content(self, request_data: dict[str, Any], content: str, page: int, page_size: int) -> dict[str, Any]:
    # 处理长行，每行限制80个字符
    display_lines = []
    for line in content.split("\n"):
        if len(line) <= 80:
            display_lines.append(line)
        else:
            display_lines.extend([
                line[i : i + 80] + (" \\" if i + 80 < len(line) else "")
                for i in range(0, len(line), 80)
            ])
    
    # 计算分页参数
    total_lines = len(display_lines)
    total_pages = (total_lines + page_size - 1) // page_size
    page = max(1, min(page, total_pages))
    
    # 获取当前页内容
    start_line = (page - 1) * page_size
    end_line = min(total_lines, start_line + page_size)
    
    # 返回分页结果
    return {
        "id": request_data.get("id"),
        "content": "\n".join(display_lines[start_line:end_line]),
        "page": page,
        "total_pages": total_pages,
        "showing_lines": f"{start_line + 1}-{end_line} of {total_lines}",
        "has_more": page < total_pages,
    }
```

## 6. 核心数据处理函数

### 6.1 请求列表处理

**功能**：获取和处理请求列表数据

**代码逻辑**：
1. 计算分页参数
2. 构建 GraphQL 查询
3. 执行查询获取数据
4. 处理返回的请求列表
5. 格式化结果并返回

**核心实现**：
```python
def list_requests(self, ...):
    # 计算分页参数
    offset = (start_page - 1) * page_size
    limit = (end_page - start_page + 1) * page_size
    
    # 构建 GraphQL 查询
    query = gql("""...""")
    
    # 执行查询
    result = self.client.execute(query, variable_values=variables)
    
    # 处理结果
    data = result.get("requestsByOffset", {})
    nodes = [edge["node"] for edge in data.get("edges", [])]
    count_data = data.get("count") or {}
    
    # 返回格式化结果
    return {
        "requests": nodes,
        "total_count": count_data.get("value", 0),
        "start_page": start_page,
        "end_page": end_page,
        "page_size": page_size,
        "offset": offset,
        "returned_count": len(nodes),
        "sort_by": sort_by,
        "sort_order": sort_order,
    }
```

### 6.2 请求详情处理

**功能**：获取和处理单个请求的详细数据

**代码逻辑**：
1. 根据请求部分（request/response）选择查询
2. 执行 GraphQL 查询获取数据
3. 解码 Base64 编码的内容
4. 根据需要进行搜索或分页
5. 格式化结果并返回

**核心实现**：
```python
def view_request(self, ...):
    # 选择查询
    queries = {
        "request": """query GetRequest($id: ID!) { ... }""",
        "response": """query GetRequest($id: ID!) { ... }""",
    }
    
    # 执行查询
    result = self.client.execute(gql(queries[part]), variable_values={"id": request_id})
    
    # 解码内容
    raw_content = request_data.get("raw")
    content = base64.b64decode(raw_content).decode("utf-8", errors="replace")
    
    # 搜索或分页处理
    if search_pattern:
        return self._search_content(request_data, content, search_pattern)
    else:
        return self._paginate_content(request_data, content, page, page_size)
```

### 6.3 内容搜索处理

**功能**：在请求/响应内容中搜索特定模式

**代码逻辑**：
1. 编译正则表达式
2. 查找所有匹配项
3. 获取每个匹配项的上下文
4. 限制匹配数量
5. 格式化结果并返回

**核心实现**：
```python
def _search_content(self, ...):
    regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    matches = []
    
    for match in regex.finditer(content):
        # 获取匹配上下文
        before = re.sub(r"\s+", " ", content[max(0, start - context_size) : start].strip())[-100:]
        after = re.sub(r"\s+", " ", content[end : end + context_size].strip())[:100]
        
        matches.append({
            "match": match.group(),
            "before": before,
            "after": after,
            "position": start
        })
        
        if len(matches) >= 20:
            break
    
    return {
        "id": request_data.get("id"),
        "matches": matches,
        "total_matches": len(matches),
        "search_pattern": pattern,
        "truncated": len(matches) >= 20,
    }
```

### 6.4 内容分页处理

**功能**：对长内容进行分页处理

**代码逻辑**：
1. 处理长行，每行限制80个字符
2. 计算总页数
3. 获取当前页内容
4. 格式化结果并返回

**核心实现**：
```python
def _paginate_content(self, ...):
    # 处理长行
    display_lines = []
    for line in content.split("\n"):
        if len(line) <= 80:
            display_lines.append(line)
        else:
            display_lines.extend([
                line[i : i + 80] + (" \\" if i + 80 < len(line) else "")
                for i in range(0, len(line), 80)
            ])
    
    # 计算分页
    total_lines = len(display_lines)
    total_pages = (total_lines + page_size - 1) // page_size
    page = max(1, min(page, total_pages))
    
    # 获取当前页
    start_line = (page - 1) * page_size
    end_line = min(total_lines, start_line + page_size)
    
    return {
        "id": request_data.get("id"),
        "content": "\n".join(display_lines[start_line:end_line]),
        "page": page,
        "total_pages": total_pages,
        "showing_lines": f"{start_line + 1}-{end_line} of {total_lines}",
        "has_more": page < total_pages,
    }
```

### 6.5 站点地图处理

**功能**：获取和处理站点地图数据

**代码逻辑**：
1. 根据父ID决定查询类型
2. 执行 GraphQL 查询获取数据
3. 清理和格式化站点地图条目
4. 分页处理结果
5. 格式化结果并返回

**核心实现**：
```python
def list_sitemap(self, ...):
    # 根据父ID选择查询
    if parent_id:
        query = gql("""...""")
        result = self.client.execute(query, variable_values={"parentId": parent_id, "depth": depth})
        data = result.get("sitemapDescendantEntries", {})
    else:
        query = gql("""...""")
        result = self.client.execute(query, variable_values={"scopeId": scope_id})
        data = result.get("sitemapRootEntries", {})
    
    # 处理结果
    all_nodes = [edge["node"] for edge in data.get("edges", [])]
    count_data = data.get("count") or {}
    total_count = count_data.get("value", 0)
    
    # 清理节点数据
    cleaned_nodes = []
    for node in paginated_nodes:
        cleaned = {
            "id": node["id"],
            "kind": node["kind"],
            "label": node["label"],
            "hasDescendants": node["hasDescendants"],
        }
        
        # 添加元数据
        if node.get("metadata") and (...):
            cleaned["metadata"] = node["metadata"]
        
        # 添加请求信息
        if node.get("request"):
            req = node["request"]
            cleaned_req = {}
            if req.get("method"):
                cleaned_req["method"] = req["method"]
            if req.get("path"):
                cleaned_req["path"] = req["path"]
            if req.get("response") and req["response"].get("statusCode"):
                cleaned_req["status"] = req["response"]["statusCode"]
            if cleaned_req:
                cleaned["request"] = cleaned_req
        
        cleaned_nodes.append(cleaned)
    
    # 返回结果
    return {
        "entries": cleaned_nodes,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "total_count": total_count,
        "has_more": page < total_pages,
        "showing": f"{skip_count + 1}-{min(skip_count + page_size, total_count)} of {total_count}",
    }
```

## 7. 数据转换与格式化

### 7.1 Base64 解码

```python
raw_content = request_data.get("raw")
content = base64.b64decode(raw_content).decode("utf-8", errors="replace")
```

### 7.2 长行处理

```python
display_lines = []
for line in content.split("\n"):
    if len(line) <= 80:
        display_lines.append(line)
    else:
        display_lines.extend([
            line[i : i + 80] + (" \\" if i + 80 < len(line) else "")
            for i in range(0, len(line), 80)
        ])
```

### 7.3 搜索结果格式化

```python
matches.append({
    "match": match.group(),
    "before": before,
    "after": after,
    "position": start
})
```

### 7.4 站点地图数据清理

```python
cleaned = {
    "id": node["id"],
    "kind": node["kind"],
    "label": node["label"],
    "hasDescendants": node["hasDescendants"],
}

if node.get("metadata") and (...):
    cleaned["metadata"] = node["metadata"]

if node.get("request"):
    req = node["request"]
    cleaned_req = {}
    if req.get("method"):
        cleaned_req["method"] = req["method"]
    if req.get("path"):
        cleaned_req["path"] = req["path"]
    if req.get("response") and req["response"].get("statusCode"):
        cleaned_req["status"] = req["response"]["statusCode"]
    if cleaned_req:
        cleaned["request"] = cleaned_req
```

## 8. 数据分析与提取

### 8.1 请求模式分析

通过 `list_requests` 方法获取请求列表后，Agent 可以分析请求模式，例如：
- 常用的 HTTP 方法
- 访问频率高的端点
- 响应时间长的请求
- 状态码分布

### 8.2 内容分析

通过 `view_request` 和 `_search_content` 方法，Agent 可以分析请求和响应内容，例如：
- 寻找敏感信息（API密钥、令牌等）
- 分析参数格式和值
- 查找潜在的漏洞模式
- 分析响应结构

### 8.3 站点地图分析

通过 `list_sitemap` 和 `view_sitemap_entry` 方法，Agent 可以分析网站结构，例如：
- 发现所有可访问的端点
- 分析端点之间的关系
- 发现隐藏或未公开的端点
- 分析不同端点的响应状态

## 9. 代码优化建议

### 9.1 批量数据处理

**问题**：当前代码一次处理一个请求，对于大量数据效率较低

**优化建议**：
```python
def batch_process_requests(self, request_ids: list[str], part: str = "request") -> dict[str, Any]:
    # 构建批量查询
    query = gql("""
        query GetMultipleRequests($ids: [ID!]!) {
            requests(ids: $ids) {
                id method host path query createdAt length isTls port
                source alteration fileExtension raw
                response { id statusCode length roundtripTime createdAt raw }
            }
        }
    """)
    
    # 执行批量查询
    result = self.client.execute(query, variable_values={"ids": request_ids})
    
    # 处理结果
    requests = result.get("requests", [])
    processed_results = {}
    
    for req in requests:
        # 处理每个请求
        # ...
        processed_results[req["id"]] = processed_data
    
    return processed_results
```

### 9.2 缓存机制

**问题**：频繁调用相同查询会导致性能问题

**优化建议**：
```python
from functools import lru_cache

# 添加缓存装饰器
@lru_cache(maxsize=100)
def cached_query(self, query: str, variables: tuple) -> dict[str, Any]:
    return self.client.execute(gql(query), variable_values=dict(variables))

# 使用缓存查询
def list_requests(self, ...):
    # ...
    variables_tuple = (limit, offset, httpql_filter, sort_by, sort_order, scope_id)
    result = self.cached_query(query_str, variables_tuple)
    # ...
```

### 9.3 异步处理

**问题**：当前代码是同步的，处理大量数据时会阻塞

**优化建议**：
```python
async def async_list_requests(self, ...):
    # 使用异步 GraphQL 客户端
    async with AsyncClient(transport=transport, fetch_schema_from_transport=False) as client:
        result = await client.execute(query, variable_values=variables)
        # 处理结果
        # ...
```

### 9.4 结果过滤优化

**问题**：当前代码在 Python 中过滤数据，效率较低

**优化建议**：
```python
def list_requests(self, ...):
    # 将过滤条件传递给 Caido API
    httpql_filter = "status_code = 200 AND method = 'GET'"
    
    variables = {
        "limit": limit,
        "offset": offset,
        "filter": httpql_filter,
        # ...
    }
    
    # 执行查询
    # ...
```

## 10. 总结

Strix 项目中 Caido 抓包数据的处理是一个复杂的过程，涉及数据获取、转换、过滤、搜索、分页和展示等多个阶段。核心实现包括：

1. **数据获取**：通过 GraphQL API 从 Caido 获取数据
2. **数据转换**：将 Caido 返回的数据转换为适合 Agent 处理的格式
3. **数据过滤**：支持通过 HTTPQL 过滤数据
4. **数据搜索**：支持在请求/响应内容中搜索特定模式
5. **数据分页**：支持对大量数据进行分页处理
6. **数据展示**：将数据格式化为易于 Agent 查看的形式
7. **数据分析**：支持从数据中提取有价值的信息

当前实现具有以下特点：

1. **模块化设计**：数据处理逻辑封装在 ProxyManager 类中，便于维护和扩展
2. **灵活的配置**：支持多种查询参数和过滤条件
3. **丰富的功能**：支持请求列表、请求详情、站点地图等多种数据处理
4. **良好的错误处理**：对各种异常情况进行了处理
5. **易于扩展**：支持添加新的数据处理方法

通过进一步优化，如添加批量处理、缓存机制、异步处理和优化结果过滤，可以进一步提高数据处理的效率和性能。