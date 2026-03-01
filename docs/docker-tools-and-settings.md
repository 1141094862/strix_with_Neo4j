# Docker 镜像工具与设置总结

## 1. 基础信息

**镜像名称**: ghcr.io/usestrix/strix-sandbox:0.1.10
**基础镜像**: kalilinux/kali-rolling:latest
**主要用途**: AI Agent 渗透测试环境，提供全面的自动化安全测试工具

## 2. 目录结构

```
+------------------------+
| 容器目录结构           |
+------------------------+
| /home/pentester/       |
|   ├── configs/         | 配置文件目录
|   ├── wordlists/       | 字典文件目录
|   ├── output/          | 输出文件目录
|   ├── scripts/         | 脚本目录
|   ├── tools/           | 工具安装目录
|   └── .npm-global/     | npm全局安装目录
+------------------------+
| /app/                  |
|   ├── certs/           | 证书目录
|   ├── runtime/         | 运行时目录
|   ├── tools/           | 工具目录
|   └── venv/            | Python虚拟环境
+------------------------+
| /workspace/            | 工作目录
+------------------------+
```

## 3. 安装的工具

### 3.1 基础工具

| 工具名称 | 安装方式 | 用途 |
|---------|---------|------|
| wget | apt-get | 网络下载工具 |
| curl | apt-get | 网络请求工具 |
| git | apt-get | 版本控制工具 |
| vim | apt-get | 文本编辑器 |
| nano | apt-get | 文本编辑器 |
| unzip | apt-get | 解压工具 |
| tar | apt-get | 归档工具 |
| jq | apt-get | JSON处理工具 |
| parallel | apt-get | 并行执行工具 |
| ripgrep | apt-get | 快速搜索工具 |
| grep | apt-get | 文本搜索工具 |
| less | apt-get | 分页查看工具 |
| man-db | apt-get | 手册页工具 |
| procps | apt-get | 进程查看工具 |
| htop | apt-get | 交互式进程查看器 |
| tmux | apt-get | 终端复用工具 |

### 3.2 开发环境

| 工具名称 | 安装方式 | 用途 |
|---------|---------|------|
| python3 | apt-get | Python3解释器 |
| pip3 | apt-get | Python包管理工具 |
| golang-go | apt-get | Go语言环境 |
| nodejs | apt-get | Node.js环境 |
| npm | apt-get | Node.js包管理工具 |
| pipx | apt-get | Python应用隔离安装工具 |
| poetry | curl | Python依赖管理工具 |

### 3.3 网络工具

| 工具名称 | 安装方式 | 用途 |
|---------|---------|------|
| net-tools | apt-get | 网络配置工具 |
| dnsutils | apt-get | DNS查询工具 |
| whois | apt-get | WHOIS查询工具 |
| iproute2 | apt-get | 网络路由工具 |
| iputils-ping | apt-get | ping工具 |
| netcat-traditional | apt-get | 网络连接工具 |
| nmap | apt-get | 网络扫描工具 |
| ncat | apt-get | 网络连接工具 |
| ndiff | apt-get | Nmap结果比较工具 |

### 3.4 安全扫描工具

| 工具名称 | 安装方式 | 用途 |
|---------|---------|------|
| sqlmap | apt-get | SQL注入检测工具 |
| nuclei | apt-get | 漏洞扫描工具 |
| subfinder | apt-get | 子域名发现工具 |
| naabu | apt-get | 端口扫描工具 |
| ffuf | apt-get | Web模糊测试工具 |
| httpx | go install | HTTP请求工具 |
| katana | go install | Web爬虫工具 |
| vulnx | go install | 漏洞扫描工具 |
| gospider | go install | Web爬虫工具 |
| interactsh-client | go install | 外带数据检测工具 |
| zaproxy | apt-get | Web应用安全扫描工具 |
| trivy | curl | 漏洞扫描工具 |
| wapiti | apt-get | Web应用安全扫描工具 |
| trufflehog | curl | 秘密检测工具 |

### 3.5 代码分析工具

| 工具名称 | 安装方式 | 用途 |
|---------|---------|------|
| semgrep | pipx | 静态代码分析工具 |
| bandit | pipx | Python代码安全分析工具 |
| eslint | npm | JavaScript代码检查工具 |
| jshint | npm | JavaScript代码检查工具 |
| js-beautify | npm | JavaScript代码格式化工具 |

### 3.6 JavaScript工具

| 工具名称 | 安装方式 | 用途 |
|---------|---------|------|
| retire | npm | JavaScript依赖漏洞检测工具 |
| JS-Snooper | git clone | JavaScript敏感信息提取工具 |
| jsniper.sh | git clone | JavaScript分析工具 |

### 3.7 JWT工具

| 工具名称 | 安装方式 | 用途 |
|---------|---------|------|
| jwt_tool | git clone | JWT令牌安全测试工具 |

### 3.8 其他工具

| 工具名称 | 安装方式 | 用途 |
|---------|---------|------|
| arjun | pipx | HTTP参数发现工具 |
| dirsearch | pipx | 目录扫描工具 |
| wafw00f | pipx | WAF检测工具 |

## 4. 证书配置

### 4.1 自签名CA证书

容器生成了自签名CA证书，用于SSL/TLS通信和代理设置：

- **证书位置**: `/app/certs/`
- **证书文件**:
  - `ca.key`: 私钥文件
  - `ca.crt`: 证书文件
  - `ca.p12`: PKCS12格式证书
- **证书属性**:
  - 有效期: 3650天
  - 主题: `/C=US/ST=CA/O=Security Testing/CN=Testing Root CA`
  - 扩展: `basicConstraints=critical,CA:TRUE`
  - 密钥用法: `critical,digitalSignature,keyEncipherment,keyCertSign`

### 4.2 证书信任配置

- 证书已添加到系统信任存储
- 证书已添加到浏览器信任存储
- 证书用于Caido代理配置

## 5. 环境变量

| 环境变量 | 默认值 | 用途 |
|---------|---------|------|
| NPM_CONFIG_PREFIX | /home/pentester/.npm-global | npm全局安装路径 |
| PATH | /home/pentester/go/bin:/home/pentester/.local/bin:/home/pentester/.npm-global/bin:/app/venv/bin:$PATH | 系统PATH变量 |
| VIRTUAL_ENV | /app/venv | Python虚拟环境路径 |
| POETRY_HOME | /opt/poetry | Poetry安装路径 |
| STRIX_SANDBOX_MODE | true | 沙箱模式开关 |
| PYTHONPATH | /app | Python模块搜索路径 |
| REQUESTS_CA_BUNDLE | /etc/ssl/certs/ca-certificates.crt | Python requests库CA证书路径 |
| SSL_CERT_FILE | /etc/ssl/certs/ca-certificates.crt | 系统SSL证书路径 |

## 6. 容器初始化流程

容器启动时，`docker-entrypoint.sh`脚本执行以下初始化步骤：

1. **检查CAIDO_PORT环境变量**
2. **启动Caido代理服务**:
   - 监听地址: 127.0.0.1:${CAIDO_PORT}
   - 允许访客访问
   - 禁用日志记录
   - 不自动打开浏览器
   - 导入自签名CA证书

3. **等待Caido API就绪**
4. **获取Caido API令牌**
5. **创建Caido项目**
6. **选择Caido项目**
7. **配置系统级代理设置**:
   - 创建`/etc/profile.d/proxy.sh`
   - 更新`/etc/environment`
   - 更新`/etc/wgetrc`
   - 更新用户bashrc和zshrc

8. **将CA证书添加到浏览器信任存储**
9. **完成初始化，进入工作目录**

## 7. 代理配置

容器使用Caido作为系统级代理，所有网络请求都通过Caido代理转发：

| 代理类型 | 代理地址 | 配置文件 |
|---------|---------|---------|
| HTTP代理 | http://127.0.0.1:${CAIDO_PORT} | /etc/profile.d/proxy.sh, /etc/environment, /etc/wgetrc |
| HTTPS代理 | http://127.0.0.1:${CAIDO_PORT} | /etc/profile.d/proxy.sh, /etc/environment, /etc/wgetrc |
| ALL代理 | http://127.0.0.1:${CAIDO_PORT} | /etc/profile.d/proxy.sh, /etc/environment |

## 8. 工具更新与维护

- **nuclei模板**: 容器构建时自动更新nuclei模板
- **工具安装方式**: 采用多种安装方式，包括apt-get、go install、pipx、npm等
- **工具版本**: 大部分工具安装最新版本

## 9. 安全设置

- **用户权限**: 创建了pentester用户，具有sudo权限（无需密码）
- **nmap权限**: 为nmap添加了CAP_NET_RAW、CAP_NET_ADMIN、CAP_NET_BIND_SERVICE权限
- **容器隔离**: 使用Docker容器提供隔离环境
- **证书安全**: 自签名CA证书用于内部通信和测试

## 10. 工具使用说明

### 10.1 常用工具示例

#### 10.1.1 网络扫描
```bash
# 使用nmap进行端口扫描
nmap -sV -sC target.com

# 使用naabu进行快速端口扫描
naabu -host target.com
```

#### 10.1.2 漏洞扫描
```bash
# 使用nuclei进行漏洞扫描
nuclei -u target.com

# 使用sqlmap进行SQL注入检测
sqlmap -u "http://target.com/vuln.php?id=1" --dbs
```

#### 10.1.3 Web测试
```bash
# 使用ffuf进行目录扫描
ffuf -u http://target.com/FUZZ -w /usr/share/wordlists/dirb/common.txt

# 使用dirsearch进行目录扫描
dirsearch -u http://target.com
```

#### 10.1.4 JavaScript分析
```bash
# 使用JS-Snooper分析JavaScript
JS-Snooper/js_snooper.sh -u http://target.com

# 使用jsniper.sh分析JavaScript
jsniper.sh/jsniper.sh -u http://target.com
```

#### 10.1.5 JWT测试
```bash
# 使用jwt_tool测试JWT令牌
jwt_tool.py eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## 11. 总结

本Docker镜像提供了一个全面的AI Agent渗透测试环境，包含了各种安全测试工具和基础设施：

1. **全面的工具集**: 包含网络扫描、漏洞检测、Web测试、代码分析等多种类型的安全工具
2. **自动化配置**: 容器启动时自动配置代理、证书和工具
3. **隔离环境**: 基于Kali Linux的隔离容器环境，适合安全测试
4. **灵活的使用方式**: 支持多种工具安装方式和使用场景
5. **便于扩展**: 可以根据需要添加新的工具和配置

该镜像适合用于AI Agent自动化安全扫描、手动渗透测试和安全研究等场景。