# 🤖 Kefu — 24H 无人值守智能电商客服系统

基于多 Agent 架构的智能客服系统，支持**淘宝**和**抖音**店铺，具备自主学习能力。
无需官方开放平台 API，通过浏览器自动化 + LLM 实现全自动回复。

---

## 目录

- [架构概览](#架构概览)
- [核心特性](#核心特性)
- [快速开始](#快速开始)
  - [Docker 一键部署](#docker-一键部署推荐)
  - [本地开发部署](#本地开发部署)
- [项目结构](#项目结构)
- [配置指南](#配置指南)
  - [AI 模型配置](#ai-模型配置)
  - [人设配置 (Persona)](#人设配置-persona)
  - [Agent 工具](#agent-工具)
  - [MCP 外部工具接入](#mcp-外部工具接入)
- [API 文档](#api-文档)
- [浏览器自动化](#浏览器自动化)
- [知识库自学习](#知识库自学习)
- [缓存系统](#缓存系统)
- [GUI 管理面板](#gui-管理面板)
- [技术栈](#技术栈)
- [架构决策](#架构决策)
- [路线图](#路线图)

---

## 架构概览

```
                     ┌──────────────────────────┐
                     │     🖥 GUI 管理面板        │
                     │   Vue 3 + Element Plus    │
                     │   http://localhost:8801   │
                     └────────────┬─────────────┘
                                  │ REST + WebSocket
                     ┌────────────▼─────────────┐
                     │      📡 API Server        │
                     │     FastAPI + Uvicorn     │
                     │   http://localhost:8800   │
                     └────────────┬─────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
┌───────▼────────┐   ┌───────────▼──────────┐   ┌─────────▼─────────┐
│  🧠 AI 引擎     │   │   🔧 Agent 工具系统   │   │  🌐 外部集成       │
│                │   │                      │   │                  │
│ · 意图分类      │   │ · WebSearch          │   │ · MCP 协议       │
│ · RAG 检索      │   │ · KnowledgeBase      │   │ · agent-browser  │
│ · Persona 注入  │   │ · CustomerMemory     │   │ · Playwright     │
│ · LLM 路由      │   │ · ProductLookup      │   │                  │
│                │   │ · ImageAnalysis      │   │                  │
└───────┬────────┘   └───────────┬──────────┘   └──────────────────┘
        │                        │
┌───────▼────────────────────────▼──────────┐
│               📊 数据层                     │
│                                            │
│  · PostgreSQL 16 + pgvector (向量检索)      │
│  · Redis 7 (缓存 + 消息队列)               │
│  · AES-256-GCM API Key 加密存储            │
│  · 三级缓存 (L1内存 / L2 Redis / L3语义)    │
└────────────────────────────────────────────┘
```

### Agent 处理流程

```
客户消息 "这件M码有货吗？什么时候能发货？"
    │
    ▼
意图分类 ──→ presale (售前咨询)
    │
    ├─ 缓存检查 (L1→L2→L3)
    │   └─ 命中? → 直接返回 (0.1-50ms)
    │
    ▼
RAG 检索 (pgvector 语义搜索)
    │
    ▼
工具调用
    ├─ product_lookup.check_stock("商品ID", "M码")  → 库存状态
    └─ product_lookup.get_shipping("商品ID")         → 发货时效
    │
    ▼
Persona 注入 (SOUL + STYLE + SKILL + MEMORY + RULES)
    │
    ▼
LLM 生成回复 (Claude / GPT / 任意兼容 API)
    │
    ▼
存入缓存 → 返回客户
```

---

## 核心特性

### 🤖 智能对话
- **多模型动态调度**: 支持 Anthropic、OpenAI、DeepSeek、豆包、千问、GLM 及任意 API 中转站
- **人设系统**: SOUL.md / STYLE.md / SKILL.md / MEMORY.md / RULES.md 五文档编译为 System Prompt
- **意图分类**: 关键词 + LLM 双模，覆盖售前/订单/售后/闲聊
- **人格化回复**: 语气自然、真人风格、自动 emoji、打字延迟模拟

### 🔧 Agent 工具
- **WebSearch**: DuckDuckGo 免费搜索，支持 Bing/SerpAPI 付费后端
- **KnowledgeBase**: 知识库 CRUD + 自动学习提交通道
- **CustomerMemory**: 客户 CRM，记忆偏好、购买历史、打标签
- **ProductLookup**: 查库存、面料、尺码、物流、价格
- **ImageAnalysis**: 多模态图片分析（瑕疵检测/色差/OCR）

### 📚 知识自学习
- 每日凌晨自动运行
- 对话清洗 → Embedding 聚类 → Q&A 抽取 → 自动入库/审核队列
- 知识缺口自动发现

### ⚡ 三级缓存
- **L1 内存**: LRU + TTL，0.1ms 响应
- **L2 Redis**: 跨进程共享，1-5ms 响应
- **L3 语义**: Embedding 余弦相似度匹配，"什么时候发货"≈"多久能发出"

### 🌐 平台适配
- **淘宝千牛**: Playwright 接管 Web 版，WebSocket 拦截 + DOM 监听
- **抖音飞鸽**: 同上，适配飞鸽 IM 协议
- **无需官方 API**: 纯浏览器自动化方案

### 🔌 扩展能力
- **MCP 协议**: 自主接入任意 MCP Server 的外部工具
- **agent-browser Skill**: 本地 CLI 浏览器自动化
- **动态 API 厂商**: GUI 中自由添加模型和中转站

---

## 快速开始

### Docker 一键部署（推荐）

```bash
# 1. 克隆项目
git clone https://github.com/lf168000680/IntelligentCustomerService.git
cd IntelligentCustomerService

# 2. 配置环境变量（可选，默认值即可运行）
cp .env.example .env

# 3. 一键启动所有服务
docker compose up -d

# 4. 查看启动日志
docker compose logs -f server

# 5. 导入种子知识库
docker exec kefu-server python scripts/seed_knowledge.py

# 6. 访问
# API 文档: http://localhost:8800/docs
# 管理面板: http://localhost:8801
```

### 本地开发部署

#### 前置条件
- Python 3.11+
- Node.js 20+
- Docker（用于 PostgreSQL + Redis）

#### 步骤

```bash
# 1. 启动数据库
docker compose up -d postgres redis

# 2. 安装 Python 依赖
cd server
pip install -r requirements.txt

# 3. 配置环境变量
cd ..
cp .env.example .env
# 编辑 .env 填入你的 API Key（或稍后在 GUI 中配置）

# 4. 初始化数据库 + 导入种子知识库
python scripts/seed_knowledge.py

# 5. 启动后端
python -m server.main
# → API: http://localhost:8800
# → Docs: http://localhost:8800/docs

# 6. 启动前端（新终端）
cd gui
npm install
npm run dev
# → GUI: http://localhost:8801
```

#### 验证安装

```bash
python scripts/quick_test.py
# 期望输出: ALL PASS
```

---

## 项目结构

```
kefu/
├── server/                          # 🐍 Python 后端
│   ├── main.py                      #   入口 (python -m server.main)
│   ├── config.py                    #   配置管理 (env + yaml + DB)
│   ├── crypto_utils.py              #   AES-256-GCM 加密工具
│   │
│   ├── llm/                         # 🔌 LLM 多模型层
│   │   ├── base.py                  #   抽象基类 + 统一数据结构
│   │   ├── anthropic_provider.py    #   Anthropic Messages API
│   │   ├── openai_provider.py       #   OpenAI Responses API
│   │   ├── openai_compat.py         #   UniversalProvider (任意兼容API)
│   │   └── router.py                #   场景路由 + 降级 + 负载均衡
│   │
│   ├── engine/                      # 🧠 AI 引擎
│   │   ├── core.py                  #   主处理管线
│   │   ├── intent.py                #   意图分类器
│   │   ├── rag.py                   #   RAG 检索器
│   │   └── persona.py               #   Persona Builder
│   │
│   ├── tools/                       # 🔧 Agent 工具系统
│   │   ├── base.py                  #   工具基类 + 注册中心
│   │   ├── web_search.py            #   网络搜索
│   │   ├── knowledge_base.py        #   知识库操作
│   │   ├── customer_memory.py       #   客户记忆
│   │   ├── product_lookup.py        #   商品查询
│   │   └── image_analysis.py        #   图片分析
│   │
│   ├── cache/                       # ⚡ 三级缓存
│   │   ├── manager.py               #   缓存调度器
│   │   ├── memory_cache.py          #   L1 内存 LRU
│   │   ├── redis_cache.py           #   L2 Redis
│   │   ├── semantic_cache.py        #   L3 语义相似度
│   │   └── hit_tracker.py           #   命中追踪
│   │
│   ├── knowledge/                   # 📚 知识自学习
│   │   └── learning_pipeline.py     #   清洗→聚类→抽取→入库
│   │
│   ├── adapters/                    # 🌍 平台适配器
│   │   ├── base.py                  #   Playwright 基类
│   │   ├── taobao.py                #   千牛适配器
│   │   ├── douyin.py                #   飞鸽适配器
│   │   └── session_manager.py       #   会话管理
│   │
│   ├── mcp/                         # 🔗 MCP 客户端
│   │   └── client.py                #   MCP 协议实现
│   │
│   ├── browser/                     # 🌐 agent-browser 适配
│   │   └── adapter.py               #   CLI 调用封装
│   │
│   ├── db/                          # 💾 数据层
│   │   ├── base.py                  #   连接引擎 + Embedding
│   │   ├── models.py                #   12张表 ORM
│   │   └── vector.py                #   pgvector 操作
│   │
│   ├── bus/                         # 📡 消息总线
│   │   └── message_bus.py           #   路由 + 去重 + 会话
│   │
│   ├── scheduler/                   # ⏰ 定时任务
│   │   └── jobs.py                  #   健康检查 + 学习 + 日报
│   │
│   └── api/                         # 🌐 REST API
│       ├── routes/                  #   9 个路由模块
│       │   ├── chat.py              #   会话接口
│       │   ├── knowledge.py         #   知识库 CRUD
│       │   ├── persona.py           #   人设管理
│       │   ├── models.py            #   AI 模型配置
│       │   ├── analytics.py         #   数据统计
│       │   ├── system.py            #   系统管理
│       │   ├── cache.py             #   缓存管理
│       │   ├── mcp.py               #   MCP 管理
│       │   └── browser.py           #   浏览器操作
│       └── websocket.py             #   实时推送
│
├── gui/                             # 🖥 Vue.js 前端
│   └── src/
│       ├── views/
│       │   ├── Dashboard.vue        #   数据总览
│       │   ├── PersonaEditor.vue    #   🎭 人设编辑器 (核心)
│       │   ├── ModelConfig.vue      #   AI 模型配置
│       │   ├── KnowledgeBase.vue    #   知识库管理
│       │   ├── LiveChat.vue         #   实时会话
│       │   ├── ToolsConfig.vue      #   Agent 工具管理
│       │   ├── Analytics.vue        #   数据统计
│       │   ├── Settings.vue         #   系统设置
│       │   └── Products.vue         #   商品管理
│       ├── api/index.js             #   后端 API 封装
│       ├── router/index.js          #   路由配置
│       └── stores/app.js            #   Pinia 状态
│
├── config/                          # ⚙️ 配置文件
│   ├── providers.yaml               #   12 个模型预设
│   ├── personas/default/            #   默认人设
│   │   ├── SOUL.md                  #   身份 + 价值观
│   │   ├── STYLE.md                 #   语气 + 话术
│   │   ├── SKILL.md                 #   能力边界
│   │   ├── MEMORY.md                #   长期记忆
│   │   └── RULES.md                 #   行为规则
│   └── skills/kefu-agent/           #   Agent 操作规则
│       └── SKILL.md                 #   工具使用 + 决策流程
│
├── scripts/                         # 🔧 工具脚本
│   ├── quick_test.py                #   快速验证
│   ├── seed_knowledge.py            #   种子数据导入 (22条FAQ)
│   └── init_db.sql                  #   PostgreSQL 初始化
│
├── tests/                           # 🧪 测试
│   ├── test_llm_router.py
│   ├── test_persona.py
│   └── test_intent.py
│
├── docker-compose.yml               # Docker 编排
├── Dockerfile (server + gui)        # 容器构建
└── README.md
```

---

## 配置指南

### AI 模型配置

API Key **不写入环境变量**，而是加密存储在 PostgreSQL 中，通过 GUI 管理。

#### 方式一：GUI 配置（推荐）

1. 打开 http://localhost:8801
2. 左侧导航 → **AI Models**
3. 点击模型的 **编辑** 按钮
4. 填入 API Key → 保存
5. 点击 **测试** 验证连通性
6. 确保 `enabled` 开关打开
7. 点击 **刷新状态**

#### 方式二：通过 API

```bash
# 添加模型
curl -X POST http://localhost:8800/api/models/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "我的DeepSeek",
    "provider": "openai_compat",
    "model_id": "deepseek-chat",
    "api_key": "sk-xxxx",
    "api_base": "https://api.deepseek.com/v1",
    "enabled": true,
    "tags": ["default", "cheap"]
  }'

# 重新加载 Router（使配置生效）
curl -X POST http://localhost:8800/api/models/reload
```

#### 预设模型

| 模型 | 厂商 | 场景 |
|------|------|------|
| Claude Sonnet 4.6 | Anthropic | default |
| Claude Haiku 4.5 | Anthropic | fast / cheap |
| Claude Opus 4.8 | Anthropic | reasoning |
| GPT-4o | OpenAI | default |
| GPT-4o-mini | OpenAI | fast / cheap |
| DeepSeek V3 | OpenAI Compat | cheap |
| 豆包 Lite | 字节跳动 | cheap |
| 通义千问 Turbo | 阿里云 | cheap |
| GLM-4 Flash | 智谱 | cheap |
| Groq Llama | Groq | cheap |
| OpenRouter | 中转站 | default |
| 自定义中转站 | 通用 | default |

#### 添加自定义 API 中转站

```json
{
  "name": "我的中转站",
  "provider": "openai_compat",
  "model_id": "gpt-4o",
  "api_key": "sk-xxxx",
  "api_base": "https://your-relay.example.com/v1",
  "headers": {"X-Custom-Auth": "token"},
  "extra_config": {"timeout": 120, "max_retries": 5}
}
```

---

### 人设配置 (Persona)

人设系统由 5 个 Markdown 文档组成，在 GUI 的 **Persona Editor** 中实时编辑和预览。

#### SOUL.md — 核心身份
```markdown
## 身份
你是「小糖」，原创女装淘宝店客服，从业3年。

## 核心价值观
- 真诚：尺码不合适主动劝退
- 耐心：每个问题都当第一次回答
- 专业：面料、版型、搭配专家
```

#### STYLE.md — 沟通风格
```markdown
## 语气
- 用"亲亲"，不用"亲"
- 每2-3句一个emoji
- 不用"您"，用"你"

## 话术示例
✅ "宝～看中哪件啦？帮你查库存哦 😊"
❌ "您好，请问有什么可以帮您的？"
```

#### SKILL.md — 能力边界
```markdown
## 我能做的
- 面料解析、尺码推荐、搭配建议
- 查物流、修改地址、催发货
- 退换货指引、质量问题判断

## 我不能做的
- ❌ 操作退款（只能引导）
- ❌ 修改商品价格
- ❌ 承诺具体到达日期
```

#### MEMORY.md — 长期记忆（自动更新）
```markdown
## 重要事件
- 2026-06-15: 夏季新品上架

## 老客户档案
- [旺旺: xxx] 回购3次，偏好法式复古，尺码M
```

#### RULES.md — 行为规则
```markdown
## 安全规则
1. 不透露运营数据
2. 不提供支付链接
3. 不索要密码验证码

## 升级规则
以下情况标记转老板：
- 客户要求退款/仅退款
- 客户威胁投诉/差评
- 客户声称是律师/工商人员
```

---

### Agent 工具

Kefu Agent 内置 5 个工具，在 `config/skills/kefu-agent/SKILL.md` 中定义使用规则。

| 工具 | 用途 | 触发场景 |
|------|------|---------|
| `web_search` | 搜索互联网 | 竞品对比、政策查询 |
| `knowledge_base` | 知识库 CRUD | FAQ 查找、知识缺口记录 |
| `customer_memory` | 客户 CRM | 老客户偏好、购买历史 |
| `product_lookup` | 商品查询 | 库存、面料、尺码、物流 |
| `image_analysis` | 图片分析 | 瑕疵检测、色差、OCR |

Agent 决策流程：
```
收到客户消息
├─ greeting → 快速问候（不用工具）
├─ presale → product_lookup + knowledge_base + web_search
├─ order → product_lookup (shipping/stock)
├─ aftersale → image_analysis + knowledge_base
├─ closing → 简单结束语
└─ other → knowledge_base + LLM 通用回复
```

---

### MCP 外部工具接入

Kefu Agent 通过 **MCP (Model Context Protocol)** 自主接入任意外部工具。

#### 工作原理

```
用户 GUI 添加 MCP Server
    ↓
Agent 启动时自动连接
    ↓
自动发现 Server 提供的工具 (tools/list)
    ↓
注册到 Agent 工具系统
    ↓
Agent 可像内置工具一样调用
```

#### 添加 MCP Server

在 GUI → Settings → MCP 中添加，或通过 API：

```bash
curl -X POST http://localhost:8800/api/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "filesystem",
    "command": "npx",
    "args": ["-y", "@anthropic/mcp-server-filesystem", "/data"],
    "transport": "stdio",
    "enabled": true,
    "description": "文件系统操作"
  }'
```

#### 支持传输方式

| 传输 | 说明 | 示例 |
|------|------|------|
| `stdio` | 本地进程通信 | npx、python、node |
| `http` | 远程 HTTP 服务 | 云函数、远程 API |

#### agent-browser Skill

agent-browser 是**本地 CLI 工具**（不是 MCP Server），通过子进程调用：

```bash
# 安装
npm install -g agent-browser

# Agent 自动调用
agent-browser navigate https://s.taobao.com/search?q=连衣裙
agent-browser extract --selector ".price"
agent-browser screenshot --selector ".product-detail"
```

---

## API 文档

启动后端后访问 http://localhost:8800/docs 查看完整的 Swagger 文档。

### 核心端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 系统健康检查 |
| POST | `/api/chat/send` | 发送消息获取 AI 回复 |
| POST | `/api/chat/test-persona` | 人设效果测试 |
| GET | `/api/chat/sessions` | 活跃会话列表 |
| GET | `/api/knowledge/` | 知识库列表 |
| POST | `/api/knowledge/` | 添加知识条目 |
| POST | `/api/knowledge/learn` | 触发自主学习 |
| GET | `/api/persona/{name}` | 获取人设文档 |
| PUT | `/api/persona/{name}/file/{file}` | 更新人设文件 |
| POST | `/api/persona/preview` | 预览人设效果 |
| GET | `/api/models/` | 模型列表 |
| POST | `/api/models/` | 添加模型 |
| POST | `/api/models/{name}/test` | 测试模型连通性 |
| POST | `/api/models/reload` | 重新加载 Router |
| GET | `/api/cache/stats` | 缓存统计 |
| GET | `/api/cache/hit-rate` | 缓存命中率 |
| POST | `/api/cache/invalidate` | 缓存失效 |
| GET | `/api/mcp/servers` | MCP Server 列表 |
| POST | `/api/mcp/servers` | 添加 MCP Server |
| GET | `/api/browser/status` | Browser 状态 |
| POST | `/api/browser/action` | 执行浏览器操作 |
| GET | `/api/system/status` | 系统全维度状态 |

### 消息发送示例

```bash
curl -X POST http://localhost:8800/api/chat/send \
  -H "Content-Type: application/json" \
  -d '{
    "message": "这件M码有货吗？",
    "user_id": "test_user_001",
    "platform": "taobao"
  }'
```

响应：
```json
{
  "reply": "亲亲～M码有的哦！现货48小时内发出 😊",
  "intent": "presale",
  "escalate": false,
  "metadata": {
    "processing_time": 1.23,
    "model_tag": "default",
    "persona": "default"
  }
}
```

---

## 浏览器自动化

### 原理

不使用淘宝/抖音官方 API，而是通过 **Playwright** 完全接管浏览器：

```
Playwright 浏览器实例
    ↓ 打开千牛/飞鸽 Web 版
    ↓ 注入 JS 拦截器
    │
    ├── WebSocket 拦截 → 获取实时消息
    ├── DOM MutationObserver → 兜底监控
    └── Fetch/XHR 拦截 → 轮询检测
```

### 适配器特性

| 特性 | 淘宝千牛 | 抖音飞鸽 |
|------|---------|---------|
| 消息监听 | ✅ WS + DOM | ✅ WS + DOM |
| 自动回复 | ✅ 模拟打字 | ✅ 模拟打字 |
| Cookie 持久化 | ✅ Profile 目录 | ✅ Profile 目录 |
| 反检测 | ✅ 指纹伪装 | ✅ 指纹伪装 |
| 登录态保持 | ✅ 心跳 + 自动恢复 | ✅ 心跳 + 自动恢复 |
| 扫码登录通知 | ✅ Webhook 通知 | ✅ Webhook 通知 |

---

## 知识库自学习

### 学习流水线（每日凌晨 2:00 自动运行）

```
Step 0: 拉取过去24h对话
    ↓
Step 1: 清洗（过滤纯表情/系统消息/隐私信息）
    ↓
Step 2: 提取客户问题（LLM 规范化）
    ↓
Step 3: Embedding 聚类（HDBSCAN/余弦相似度）
    ↓
Step 4: 生成标准 Q&A + 优化
    ↓
Step 5: 入库决策
    ├── 置信度 ≥ 0.85 → 自动入库
    ├── 置信度 ≥ 0.6 → 审核队列（GUI 审核）
    └── 置信度 < 0.6 → 丢弃
    ↓
Step 6: 发现知识缺口
    ↓
Step 7: 更新 MEMORY.md
    ↓
Step 8: 生成日报
```

### 手动触发

```bash
curl -X POST http://localhost:8800/api/knowledge/learn?days_back=1
```

---

## 缓存系统

```
客户消息
    │
    ▼
L1 内存精确匹配 (0.1ms)
    ├─ 命中 → 返回（相同消息秒回）
    │
    ▼ 未命中
L2 Redis 精确匹配 (1-5ms)
    ├─ 命中 → 返回 + 回填L1
    │
    ▼ 未命中
L3 Embedding 语义匹配 (10-50ms)
    "什么时候发货" ≈ "多久能发出" → 余弦相似度>0.85
    ├─ 命中 → 返回 + 回填L1+L2
    │
    ▼ 未命中
LLM 调用 (1-3s) → 存入L1+L2+L3
```

### 缓存 API

```bash
# 查看命中率
curl http://localhost:8800/api/cache/hit-rate

# 查看命中最多的 TOP 问题
curl http://localhost:8800/api/cache/top

# 清空缓存
curl -X POST http://localhost:8800/api/cache/invalidate?clear_all=true

# 开关缓存
curl -X PUT http://localhost:8800/api/cache/toggle
```

---

## GUI 管理面板

### 页面功能

| 页面 | 功能 |
|------|------|
| **Dashboard** | 4 卡片统计 + 实时会话表 + 模型健康状态 |
| **Live Chat** | 实时会话看板，手动回复，查看对话历史 |
| **Knowledge Base** | 知识库 CRUD + 审核队列 + 知识缺口管理 |
| **Persona Editor** 🎭 | Markdown 编辑器 + Prompt 预览 + 对话测试 |
| **AI Models** | 模型增删改查 + API Key 管理 + 连通性测试 |
| **Agent Tools** | 工具列表 + 启用/禁用 + 测试 |
| **Products** | 商品同步 + 查看 |
| **Analytics** | 数据统计 + 趋势 |
| **Settings** | 适配器管理 + MCP 配置 + 系统状态 |

### Persona Editor（核心页面）

- 左侧：Dark theme Markdown 编辑器
- 右上：编译后的 System Prompt 预览
- 右下：对话测试（即时验证人设效果）
- 支持 SOUL/STYLE/SKILL/MEMORY/RULES 5 个 Tab
- 保存后实时生效

---

## 技术栈

### 后端
| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 主语言 |
| FastAPI | 0.115 | REST API |
| Uvicorn | 0.30 | ASGI 服务器 |
| SQLAlchemy 2 | 2.0 | ORM |
| pgvector | 0.3 | 向量检索 |
| PostgreSQL | 16 | 主数据库 |
| Redis | 7 | 缓存 / 消息队列 |
| Playwright | 1.47 | 浏览器自动化 |
| Sentence-Transformers | 3.1 | Embedding 模型 |
| cryptography | 43.0 | AES-256-GCM 加密 |
| APScheduler | 3.10 | 定时任务 |
| Loguru | 0.7 | 日志 |

### 前端
| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.5 | 前端框架 |
| Element Plus | 2.8 | UI 组件库 |
| Pinia | 2.2 | 状态管理 |
| Vue Router | 4.4 | 路由 |
| Axios | 1.7 | HTTP 客户端 |
| Vite | 5.4 | 构建工具 |

### LLM SDK
| SDK | 用途 |
|-----|------|
| anthropic | Anthropic Messages API |
| openai | OpenAI + 兼容协议 |

### 基础设施
| 技术 | 用途 |
|------|------|
| Docker Compose | 容器编排 |
| Nginx | GUI 静态服务 + 反向代理 |
| Git | 版本控制 |

---

## 架构决策

### 为什么 API Key 存数据库而不是环境变量？
- ✅ GUI 中直接管理，无需重启
- ✅ 多 Key 动态切换
- ✅ AES-256-GCM 加密存储
- ✅ 支持团队协作（不同人有不同 Key）

### 为什么不用 ProviderType 枚举？
- ✅ 用户可自由添加任意 API 厂商和中转站
- ✅ 字符串标识更灵活
- ✅ 通过 `api_base` + `headers` + `extra_config` 适配任何服务

### 为什么用三级缓存？
- ✅ L1 内存：重复问题毫秒回（80% 客服消息是重复的）
- ✅ L2 Redis：跨进程/跨重启共享
- ✅ L3 语义："什么时候发货"和"多久能发出"命中同一缓存

### 为什么 agent-browser 是 CLI 而不是 MCP Server？
- agent-browser 是本地安装的单一功能 Skill
- MCP 是通用协议，用于接入多种外部工具
- CLI 调用更简单直接，MCP 更灵活可扩展
- 两者互补：CLI 处理浏览器，MCP 处理其他外部服务

---

## 路线图

### v1.1（计划中）
- [ ] GPT-4V / Claude Vision 多模态支持增强
- [ ] 语音消息支持（ASR + TTS）
- [ ] 更多平台适配（拼多多、京东、快手）
- [ ] 定时主动营销消息

### v1.2（计划中）
- [ ] 多店铺管理
- [ ] A/B 话术测试
- [ ] 客户情绪分析仪表盘
- [ ] 自动生成运营周报

### v2.0（远期）
- [ ] 插件市场
- [ ] 微信/企业微信/钉钉多渠道
- [ ] 视频号直播客服
- [ ] 大促活动自动话术切换

---

## License

MIT License

---

## 联系方式

- Issues: https://github.com/lf168000680/IntelligentCustomerService/issues
- 启动问题请先运行 `python scripts/quick_test.py` 检查环境
