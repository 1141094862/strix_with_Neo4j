# **Strix 架构增强总结：Neo4j 集成**

本次二次开发通过引入 Neo4j 图数据库，将 Strix 的数据流与控制流分离，主要实现了以下功能增强与流程改进：

## **一、 新增核心功能**

1. **旁路数据自动入库 (Auto-Ingestion)**  
   * 在底层工具执行（如 Nmap、Caido、浏览器）完成后，系统通过正则或代码自动提取关键实体（Target, Endpoint, Service, Credential, Vulnerability）。  
   * 提取的数据直接存入 Neo4j，替代了原版将长文本日志直接塞入大模型上下文的做法。  
2. **关系图谱自动构建 (Relational Graphing)**  
   * 存入数据的同时，自动建立节点间的关联（例如，将新发现的漏洞或端点自动关联至其所属的 Target 节点）。  
   * 形成结构化的资产与攻击面拓扑图。  
3. **上下文动态注入 (Dynamic Context Injection)**  
   * 重构记忆管理模块，Agent 每次发起对话请求前，系统会自动查询 Neo4j 中当前 Target 的最新拓扑状态。  
   * 将查询结果封装为 \<neo4j_context\> 标签，动态注入到 Agent 的 System Prompt 中。  
4. **主动查询工具 (Active Memory Retrieval)**  
   * 为大模型新增 query_memory 工具。  
   * Agent 遇到需要回顾的历史细节时，可主动调用该工具向 Neo4j 发起检索，获取精确数据。

## **二、 流程与场景增强**

1. **会话持久化与断点续传**  
   * 渗透测试发现的数据跨会话持久保存。系统重启或任务中断后，Agent 可通过读取 Neo4j 图谱状态，直接恢复到中断前的渗透阶段继续工作。  
2. **上下文污染控制与成本降低**  
   * 冗长的工具原始输出不再进入 LLM 的对话历史（仅保留简短执行摘要），大幅降低了 API Token 的消耗，同时避免了长文本导致的 LLM 关键信息遗忘问题。  
3. **前置知识注入与半路接管 (人机协同)**  
   * 支持安全测试人员手动或通过第三方扫描工具，提前将已知情报（如已知凭证、隐藏接口）写入 Neo4j 数据库。  
   * Agent 启动后读取图谱，可自动跳过基础信息收集阶段，直接基于已有情报进行漏洞利用或深度测试。  
4. **跨 Agent 知识共享**  
   * 所有连接到该 Neo4j 数据库的 Agent 实例共享同一套资产图谱，实现多 Agent 协同作业时的情报互通。

---

## **三、环境安装指南**

### 3.1 系统要求

| 组件 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 或 Linux |
| Python | 3.12+ |
| Docker | Docker Desktop (Windows) 或 Docker Engine (Linux) |
| Git | 最新版本 |

---

### 3.2 Windows 环境安装指南

#### 步骤 1：进入项目目录

```powershell
cd D:\strix-main
```

#### 步骤 2：安装 Poetry（Python 包管理器）

```powershell
# 使用 pip 安装 Poetry
pip install poetry

# 或者使用官方安装脚本
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```

#### 步骤 3：安装项目依赖

```powershell
# 安装所有依赖
poetry install

# 激活虚拟环境
poetry shell
```

#### 步骤 4：安装 Playwright 浏览器

```powershell
# 安装 Playwright 浏览器
playwright install chromium
```

#### 步骤 5：配置环境变量

在项目根目录 `strix-main` 下创建 `.env` 文件：

```powershell
# 创建 .env 文件
New-Item -Path ".env" -ItemType "file" -Force
```

编辑 `.env` 文件，添加以下内容：

```env
# LLM 配置（必填）
STRIX_LLM=openai/glm-4
LLM_API_KEY=your-api-key-here
LLM_API_BASE=https://openai-api-endpoint/v1

# Neo4j 配置（可选，使用默认值）
NEO4J_PASSWORD=strixpassword
NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687
```

#### 步骤 6：启动 Docker Desktop

确保 Docker Desktop 已启动并运行：

```powershell
# 检查 Docker 状态
docker ps
```

#### 步骤 7：运行 Strix

```powershell
# 在项目虚拟环境中运行
strix -t http://target-url:port
```

#### Windows Neo4j 数据持久化

Neo4j 数据默认存储在用户主目录：

```
C:\Users\<username>\.strix\neo4j\data\
```

如需备份数据，复制此目录即可。

#### Windows 常见问题

**问题 1：Poetry 安装失败**

```powershell
# 尝试使用国内镜像
pip install poetry -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**问题 2：Docker 连接失败**

```powershell
# 确保 Docker Desktop 正在运行
# 检查 Docker 服务状态
Get-Service docker
```

**问题 3：Playwright 安装失败**

```powershell
# 手动安装浏览器
playwright install chromium
# 如果失败，尝试安装所有依赖
playwright install-deps chromium
```

---

### 3.3 Linux 环境安装指南 **(此环境未进行测试)**

#### 步骤 1：进入项目目录

```bash
cd /path/to/strix-main
```

#### 步骤 2：安装 Poetry（Python 包管理器）

```bash
# 使用 pip 安装 Poetry
pip install poetry

# 或者使用官方安装脚本
curl -sSL https://install.python-poetry.org | python3 -
```

#### 步骤 3：安装项目依赖

```bash
# 安装所有依赖
poetry install

# 激活虚拟环境
poetry shell
```

#### 步骤 4：安装 Playwright 浏览器

```bash
# 安装 Playwright 浏览器
playwright install chromium

# 安装系统依赖（如果需要）
playwright install-deps chromium
```

#### 步骤 5：配置环境变量

在项目根目录 `strix-main` 下创建 `.env` 文件：

```bash
# 创建 .env 文件
touch .env
```

编辑 `.env` 文件，添加以下内容：

```env
# LLM 配置（必填）
STRIX_LLM=openai/glm-4
LLM_API_KEY=your-api-key-here
LLM_API_BASE=https://openai-api-endpoint/v1

# Neo4j 配置（可选，使用默认值）
NEO4J_PASSWORD=strixpassword
NEO4J_HTTP_PORT=7474
NEO4J_BOLT_PORT=7687
```

#### 步骤 6：启动 Docker

确保 Docker 服务已启动：

```bash
# 启动 Docker 服务（如果未启动）
sudo systemctl start docker

# 检查 Docker 状态
docker ps
```

#### 步骤 7：运行 Strix

```bash
# 在项目虚拟环境中运行
strix -t http://target-url:port
```

#### Linux Neo4j 数据持久化

Neo4j 数据默认存储在用户主目录：

```
~/.strix/neo4j/data/
```

如需备份数据，复制此目录即可。
