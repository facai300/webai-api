# WebAI-to-API 使用手册

## 简介

将浏览器端的 LLM（Gemini / DeepSeek）转为本地 API，支持智能体（Agent）直接接入。

```
浏览器 LLM → WebAI-to-API → 你的 Agent
```

---

## 快速开始

### 安装

```bash
# 安装依赖
poetry install

# 生成配置文件
cp config.conf.example config.conf
```

### 启动

```bash
# 默认启动（localhost:6969）
poetry run python src/run.py

# 自定义端口
poetry run python src/run.py --host 0.0.0.0 --port 8000

# 开发模式（热重载）
poetry run python src/run.py --reload
```

启动后终端会显示所有可用端点，访问 `http://localhost:6969/docs` 可查看 Swagger 文档。

---

## 配置

### Gemini（通过浏览器 Cookie）

Gemini 使用 `browser-cookie3` 自动从浏览器提取 Cookie，也可以手动粘贴。

```ini
[Browser]
name = chrome                          # 浏览器类型

[Cookies]
gemini_cookie_1psid =                  # 留空则自动提取
gemini_cookie_1psidts =                # 留空则自动提取

[AI]
default_model_gemini = gemini-3-flash  # 默认模型
```

支持自动提取的浏览器：`chrome`, `firefox`, `brave`, `edge`

### DeepSeek（通过 Auth Token）

DeepSeek 先尝试自动提取，失败则需要手动配置。

**首次使用**：只要在 Chrome 里登录过 https://chat.deepseek.com，启动服务时会**自动从浏览器 LevelDB 提取** token 并保存到 config.conf，无需手动操作。

```ini
[DeepSeek]
auth_token =                            # 留空则自动提取
default_model_deepseek = deepseek-v3     # 默认模型
```

**手动获取 token**（如果自动提取失败）：
1. 打开 https://chat.deepseek.com 并登录
2. 按 F12 打开开发者工具
3. 进入 Application → Local Storage → `https://chat.deepseek.com`
4. 找到 `userToken`，复制 `Value` 字段
5. 粘贴到 `config.conf` 的 `auth_token =`

### 启用/关闭服务

```ini
[EnabledAI]
gemini = true     # 启用 Gemini
deepseek = true   # 启用 DeepSeek
```

设为 `false` 可在启动时跳过初始化，不影响其他服务。

---

## API 端点参考

### DeepSeek 端点

| 端点 | 功能 | 流式 |
|---|---|---|
| `POST /deepseek` | 无状态生成 | ❌ |
| `POST /deepseek-chat` | 有状态对话（保持上下文） | ❌ |
| `POST /deepseek/stream` | 流式输出（SSE，OpenAI 兼容格式） | ✅ |

**请求体**：
```json
{
  "message": "你的问题",
  "model": "deepseek-v3",
  "thinking_enabled": null,
  "search_enabled": null,
  "stream": false
}
```

**可用 model 值**：
| model | 说明 |
|---|---|
| `deepseek-v3` | 标准对话 |
| `deepseek-r1` | 深度思考 |
| `deepseek-v3-search` | 对话 + 联网搜索 |
| `deepseek-r1-search` | 深度思考 + 联网搜索 |

**示例**：
```bash
curl -X POST http://localhost:6969/deepseek \
  -H "Content-Type: application/json" \
  -d '{"message": "用Python写一个快排", "model": "deepseek-v3"}'

# 深度思考模式
curl -X POST http://localhost:6969/deepseek \
  -H "Content-Type: application/json" \
  -d '{"message": "证明根号2是无理数", "model": "deepseek-r1"}'

# 有状态多轮对话
curl -X POST http://localhost:6969/deepseek-chat \
  -H "Content-Type: application/json" \
  -d '{"message": "记住数字42"}'
curl -X POST http://localhost:6969/deepseek-chat \
  -H "Content-Type: application/json" \
  -d '{"message": "我刚才说了什么？"}'

# 流式输出（SSE）
curl -X POST http://localhost:6969/deepseek/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "数到5", "stream": true}'
```

### Gemini 端点

| 端点 | 功能 |
|---|---|
| `POST /gemini` | 无状态生成 |
| `POST /gemini-chat` | 有状态对话 |

```bash
curl -X POST http://localhost:6969/gemini \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "model": "gemini-3-flash"}'
```

### OpenAI 兼容端点

| 端点 | 功能 |
|---|---|
| `POST /v1/chat/completions` | OpenAI 格式（当前由 Gemini 驱动） |
| `GET /v1/models` | 列出可用模型 |

```bash
curl -X POST http://localhost:6969/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3-flash",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### 其他端点

| 端点 | 功能 |
|---|---|
| `POST /translate` | 翻译（基于 Gemini） |
| `GET /v1/gems` | 列出 Gemini Gems |
| `POST /google-generatives` | Google Generative AI API |

---

## Agent 接入指南

### 方案一：OpenAI SDK（最简单）

如果 Agent 框架支持 OpenAI 客户端，只需要改 `base_url` 和 `api_key`：

```python
from openai import OpenAI

# 连接到本地的 DeepSeek（通过 OpenAI 兼容端点）
client = OpenAI(
    base_url="http://localhost:6969/v1",
    api_key="not-needed",  # 本地服务不需要 key
)

response = client.chat.completions.create(
    model="deepseek-v3",
    messages=[{"role": "user", "content": "你好！"}],
)
print(response.choices[0].message.content)
```

```python
from openai import OpenAI

# 连接到本地的 Gemini
client = OpenAI(
    base_url="http://localhost:6969/v1",
    api_key="not-needed",
)

response = client.chat.completions.create(
    model="gemini-3-flash",
    messages=[{"role": "user", "content": "你好！"}],
)
print(response.choices[0].message.content)
```

### 方案二：直接调用 API 端点

```python
import httpx
import json

DEEPSEEK_URL = "http://localhost:6969/deepseek"
GEMINI_URL = "http://localhost:6969/gemini"

def ask_deepseek(message: str, model: str = "deepseek-v3") -> str:
    """调用 DeepSeek"""
    resp = httpx.post(DEEPSEEK_URL, json={
        "message": message,
        "model": model,
    })
    return resp.json()["response"]

def ask_gemini(message: str, model: str = "gemini-3-flash") -> str:
    """调用 Gemini"""
    resp = httpx.post(GEMINI_URL, json={
        "message": message,
        "model": model,
    })
    return resp.json()["response"]

# 使用
print(ask_deepseek("用Python写个快排", "deepseek-r1"))
print(ask_gemini("解释量子计算"))
```

### 方案三：流式接入

```python
import httpx
import json

def stream_deepseek(message: str):
    """流式读取 DeepSeek 响应"""
    with httpx.stream(
        "POST",
        "http://localhost:6969/deepseek/stream",
        json={"message": message, "model": "deepseek-v3"},
        timeout=None,
    ) as resp:
        for line in resp.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                chunk = json.loads(line[6:])
                content = chunk["choices"][0]["delta"].get("content", "")
                if content:
                    print(content, end="", flush=True)

stream_deepseek("写一首诗")
```

### 方案四：LangChain / 流行 Agent 框架

```python
from langchain_openai import ChatOpenAI

# 接入 DeepSeek
llm = ChatOpenAI(
    base_url="http://localhost:6969/v1",
    api_key="not-needed",
    model="deepseek-v3",
)

# 接入 Gemini
llm = ChatOpenAI(
    base_url="http://localhost:6969/v1",
    api_key="not-needed",
    model="gemini-3-flash",
)

# 使用
response = llm.invoke("你好")
print(response.content)
```

### 方案五：两个 Agent 分别接不同模型

```python
from openai import OpenAI

# Agent A：接 DeepSeek（适合编码、推理类任务）
agent_deepseek = OpenAI(
    base_url="http://localhost:6969/v1",
    api_key="not-needed",
)
agent_deepseek.base_url = "http://localhost:6969/v1"

# Agent B：接 Gemini（适合多模态、创意类任务）
agent_gemini = OpenAI(
    base_url="http://localhost:6969/v1",
    api_key="not-needed",
)

def agent_a_task(prompt: str) -> str:
    resp = agent_deepseek.chat.completions.create(
        model="deepseek-r1",  # 深度思考模式
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content

def agent_b_task(prompt: str) -> str:
    resp = agent_gemini.chat.completions.create(
        model="gemini-3-flash",
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content

# 使用
code = agent_a_task("实现一个二分查找")
poem = agent_b_task("写一首关于AI的诗")
```

---

## 选择建议

| 场景 | 推荐模型 | 端点 |
|---|---|---|
| 编程、算法、推理 | DeepSeek R1 | `/deepseek` `model=deepseek-r1` |
| 日常对话、翻译 | DeepSeek V3 / Gemini | `/deepseek` 或 `/gemini` |
| 联网搜索 | DeepSeek + search | `model=deepseek-v3-search` |
| 流式输出 | DeepSeek stream | `/deepseek/stream` |
| OpenAI 兼容客户端 | 两者均可 | `/v1/chat/completions` |
| 多模态（图片） | Gemini | `/gemini` 传 `files` 参数 |

---

## 常见问题

### 服务器启动后端点返回 503
服务正在初始化，Gemini 初始化可能需要 5-10 秒。等待启动完成即可。

### DeepSeek 返回空内容
一般是 token 过期。重新登录 https://chat.deepseek.com，获取新的 userToken 更新到 config.conf。

### Gemini 提示 UNAUTHENTICATED
浏览器 Cookie 过期。重新在浏览器中登录 https://gemini.google.com。

### 如何切换服务器模式？
启动后按 `1` 切 WebAI(Gemini/DeepSeek) 模式，按 `2` 切 g4f 模式。
