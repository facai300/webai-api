# OpenClaw 接入教程

## 简介

OpenClaw 是一个桌面 AI 客户端，支持接入自定义 API。本教程说明如何将 OpenClaw 连接到本地的 WebAI-to-API 服务，使用 DeepSeek、Gemini 和 ChatGPT。

---

## 一、启动服务

```bash
cd WebAI-to-API
poetry run python src/run.py
```

启动后终端显示类似：

```
🚀 WebAI-to-API Server is RUNNING (Primary Mode) 🚀  
  - http://localhost:6969/v1/chat/completions
  - http://localhost:6969/deepseek
  - http://localhost:6969/gemini
  - http://localhost:6969/gpt
```

---

## 二、OpenClaw 配置

### 添加自定义 Provider

打开 OpenClaw → 设置 → 添加自定义 Provider，填入：

```
名称:            WebAI
Base URL:        http://localhost:6969/v1
API Key:         sk-local                    (任意值，服务端不校验)
API 类型:        OpenAI Compatible
```

### 添加模型

在同一个 Provider 下添加以下模型：

| 模型 ID | 名称 | 说明 |
|---|---|---|
| `deepseek-v3` | DeepSeek V3 | 标准对话 |
| `deepseek-r1` | DeepSeek R1 | 深度思考/推理 |
| `gemini-3-flash` | Gemini Flash | 快速对话 |
| `gemini-3-pro` | Gemini Pro | 强模型 |
| `gpt-4o` | ChatGPT | 通过逆向 API 调用 |

### 配置示例

```json
{
  "provider": {
    "name": "WebAI",
    "baseUrl": "http://localhost:6969/v1",
    "apiKey": "sk-local",
    "api": "openai-completions",
    "models": [
      {
        "id": "deepseek-v3",
        "name": "DeepSeek V3",
        "input": ["text"],
        "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
        "contextWindow": 16000,
        "maxTokens": 4096
      },
      {
        "id": "deepseek-r1",
        "name": "DeepSeek R1",
        "input": ["text"],
        "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
        "contextWindow": 16000,
        "maxTokens": 4096
      },
      {
        "id": "gemini-3-flash",
        "name": "Gemini Flash",
        "input": ["text"],
        "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
        "contextWindow": 32000,
        "maxTokens": 8192
      },
      {
        "id": "gemini-3-pro",
        "name": "Gemini Pro",
        "input": ["text"],
        "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
        "contextWindow": 32000,
        "maxTokens": 8192
      },
      {
        "id": "gpt-4o",
        "name": "ChatGPT",
        "input": ["text"],
        "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
        "contextWindow": 8000,
        "maxTokens": 4096
      }
    ]
  }
}
```

---

## 三、验证

在 OpenClaw 中选择 `WebAI / DeepSeek V3`，发送消息：

```
User: 你好
Assistant: 你好！有什么可以帮你的吗？
```

切换模型测试其他模型：

```
WebAI / DeepSeek R1    → 适合编程、数学、推理
WebAI / Gemini Flash   → 适合日常对话
WebAI / ChatGPT        → 需要配置 access_token
```

---

## 四、查看日志

OpenClaw 请求时，服务器终端会显示：

```
[DeepSeek] POST /v1/chat/completions model=deepseek-v3 msg="你好"
[DeepSeek] OK model=deepseek-v3 32 chars in 2.3s
```

---

## 五、注意事项

1. **必须先启动 WebAI-to-API 服务**，再打开 OpenClaw
2. **Gemini** 需要 Firefox 登录 gemini.google.com（自动提取 cookie）
3. **ChatGPT** 需要配置 `access_token` 在 `config.conf` 中
4. **DeepSeek** 开箱即用，token 会自动从浏览器提取
5. 所有模型都是**免费**的（通过网页版逆向调用）
