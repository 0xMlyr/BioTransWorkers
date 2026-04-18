# LLM API 使用文档

## 基本信息

| 项目 | 值 |
|------|-----|
| API端点 | `https://aidmx.cqtbi.edu.cn/v1` |
| 认证方式 | Bearer Token |
| Token | `sk-g4A9IFICIxhvLz87Dl7ZmceRhlBlio5p_L1FPA4VNtY` |
| 格式 | OpenAI兼容 |
| QPS限制 | 55/分钟 (~1.1秒/请求) |

---

## 可用模型

### 术语翻译推荐模型

| 模型ID | 简称 | 状态 | 稳定性 | 推荐参数 |
|--------|------|------|--------|----------|
| `cqtbi-glm5` | GLM5 | ✅ 可用 | ⭐⭐⭐ 最稳定 | t=0.01, p=0.1 |
| `cqtbi-deepseek-v3-2` | DKV3 | ✅ 可用 | ⭐⭐ 轻微波动 | t=0.01, p=0.1 |

---

## API端点

### 1. 对话补全 (Chat Completions)

**端点**: `POST /v1/chat/completions`

**请求头**:
```http
Authorization: Bearer sk-g4A9IFICIxhvLz87Dl7ZmceRhlBlio5p_L1FPA4VNtY
Content-Type: application/json
```

**请求体**:
```json
{
  "model": "cqtbi-glm5",
  "messages": [
    {
      "role": "system",
      "content": "你是昆虫学专业术语翻译助手。只输出最准确的中文术语，不加解释。"
    },
    {
      "role": "user",
      "content": "翻译：abdominal sternum 9"
    }
  ],
  "temperature": 0.01,
  "top_p": 0.1,
  "max_tokens": 50,
  "stream": false
}
```

**响应**:
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "cqtbi-glm5",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "第九腹板"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 45,
    "completion_tokens": 5,
    "total_tokens": 50
  }
}
```


---

## 可调参数详解

### 术语翻译推荐配置

```json
{
  "temperature": 0.01,    // 强制选择概率最高的词
  "top_p": 0.1,           // 仅在最确定的10%词中选择
  "max_tokens": 50,       // 限制输出长度，防废话
  "stream": false         // 非流式，简化处理
}
```

### 参数说明

| 参数 | 范围 | 术语翻译推荐 | 说明 |
|------|------|--------------|------|
| `temperature` | 0-2 | **0.01** | 低值=确定性输出，高值=创造性 |
| `top_p` | 0-1 | **0.1** | 核采样阈值，低值=保守选择 |
| `max_tokens` | 1-4096 | **50** | 最大输出长度 |
| `stream` | true/false | **false** | 流式输出开关 |
| `presence_penalty` | -2~2 | 0 | 重复惩罚 |
| `frequency_penalty` | -2~2 | 0 | 频率惩罚 |

### 参数选择策略

**超保守 (最确定)**:
```json
{
  "temperature": 0.01,
  "top_p": 0.1,
  "max_tokens": 50
}
```

**保守 (平衡)**:
```json
{
  "temperature": 0.1,
  "top_p": 0.3,
  "max_tokens": 100
}
```

---

## 代码示例

### 基础翻译 (Python + requests)

```python
import requests
import time

API_URL = "https://aidmx.cqtbi.edu.cn/v1"
API_KEY = "sk-g4A9IFICIxhvLz87Dl7ZmceRhlBlio5p_L1FPA4VNtY"

def translate_term(term_en):
    """翻译单个术语"""
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "cqtbi-glm5",  # 最稳定
        "messages": [
            {
                "role": "system",
                "content": "你是昆虫学专业术语翻译助手。只输出最准确的中文术语，不加解释。"
            },
            {
                "role": "user",
                "content": f"翻译：{term_en}"
            }
        ],
        "temperature": 0.01,
        "top_p": 0.1,
        "max_tokens": 50,
        "stream": False
    }
    
    resp = requests.post(
        f"{API_URL}/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
    
    resp.raise_for_status()
    data = resp.json()
    
    return data["choices"][0]["message"]["content"].strip()

# 使用
result = translate_term("abdominal sternum 9")
print(result)  # 第九腹板
```

### 带QPS控制的批量翻译

```python
import requests
import time

class TermTranslator:
    def __init__(self, api_key, base_url="https://aidmx.cqtbi.edu.cn/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.last_request = 0
        self.min_interval = 60.0 / 55  # 55 QPS限制
    
    def _wait_qps(self):
        """等待以符合QPS限制"""
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request = time.time()
    
    def translate(self, term, context=""):
        """翻译单个术语"""
        self._wait_qps()
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        user_msg = f"翻译：{term}"
        if context:
            user_msg += f"\n领域：{context}"
        
        payload = {
            "model": "cqtbi-glm5",
            "messages": [
                {
                    "role": "system",
                    "content": "你是昆虫学专业术语翻译助手。只输出最准确的中文术语，不加解释。"
                },
                {"role": "user", "content": user_msg}
            ],
            "temperature": 0.01,
            "top_p": 0.1,
            "max_tokens": 50,
            "stream": False
        }
        
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            # 清理常见前缀
            for prefix in ["翻译：", "中文：", "中文术语：", "译文："]:
                content = content.replace(prefix, "")
            return content.strip()
        else:
            return f"[ERROR {resp.status_code}]"
    
    def translate_batch(self, terms, context=""):
        """批量翻译术语列表"""
        results = {}
        for term in terms:
            results[term] = self.translate(term, context)
        return results

# 使用
translator = TermTranslator("sk-g4A9...")

terms = [
    "sequential hermaphroditic organism",
    "synchronous hermaphroditic organism",
    "abdominal sternum 9",
    "anterior tentorial pit",
    "median mesoscutal sulcus"
]

results = translator.translate_batch(terms, context="昆虫学")
for en, zh in results.items():
    print(f"{en} -> {zh}")
```

### 嵌入向量获取

```python
import requests

def get_embedding(text, model="cqtbi-qwen3-embedding"):
    """获取文本的嵌入向量"""
    
    headers = {
        "Authorization": "Bearer sk-g4A9IFICIxhvLz87Dl7ZmceRhlBlio5p_L1FPA4VNtY",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "input": text
    }
    
    resp = requests.post(
        "https://aidmx.cqtbi.edu.cn/v1/embeddings",
        headers=headers,
        json=payload,
        timeout=30
    )
    
    if resp.status_code == 200:
        data = resp.json()
        return data["data"][0]["embedding"]
    else:
        return None

# 使用
embedding = get_embedding("测试文本")
print(f"向量维度: {len(embedding)}")
print(f"前5维: {embedding[:5]}")
```

### cURL 命令示例

**翻译术语**:
```bash
curl -X POST "https://aidmx.cqtbi.edu.cn/v1/chat/completions" \
  -H "Authorization: Bearer sk-g4A9IFICIxhvLz87Dl7ZmceRhlBlio5p_L1FPA4VNtY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "cqtbi-glm5",
    "messages": [
      {"role": "system", "content": "翻译术语，只输出中文。"},
      {"role": "user", "content": "abdominal sternum 9"}
    ],
    "temperature": 0.01,
    "top_p": 0.1,
    "max_tokens": 50
  }'
```

**获取嵌入**:
```bash
curl -X POST "https://aidmx.cqtbi.edu.cn/v1/embeddings" \
  -H "Authorization: Bearer sk-g4A9IFICIxhvLz87Dl7ZmceRhlBlio5p_L1FPA4VNtY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "cqtbi-qwen3-embedding",
    "input": "测试文本"
  }'
```

---

## 测试结论

### 模型稳定性测试 (同一术语调用3次)

| 模型 | 输出一致性 | 备注 |
|------|-----------|------|
| GLM5 | ✅ 完全一致 | 3次输出相同 |
| DKV3 | ⚠️ 轻微波动 | 偶变体，如"中央沟"→"中沟" |
| KIMI2.5 | ❌ 不稳定 | 有时输出长解释文字 |

### 术语翻译结果对比

| 英文术语 | GLM5 | DKV3 | KIMI2.5 |
|---------|------|------|---------|
| abdominal sternum 9 | 第九腹板 | 第九腹板 | 第9腹板 |
| anterior tentorial pit | 前幕骨陷 | 前幕骨陷 | 前幕骨陷凹 |
| median mesoscutal sulcus | 中胸盾片中沟 | 中胸盾片中央沟 | 中胸背板中沟 |

### 推荐

1. **首选 GLM5** (`cqtbi-glm5`)
   - 低温度下极度稳定
   - 输出简洁一致
   - 推荐参数: `temperature=0.01, top_p=0.1`

2. **备选 DKV3** (`cqtbi-deepseek-v3-2`)
   - 响应速度快
   - 偶有轻微波动
   - 相同参数配置

---

## 注意事项

1. **QPS限制**: 严格控制在55/分钟，超过可能被封IP
2. **超时处理**: 建议设置30秒超时，GLM4/Qwen3.5可能超时
3. **输出清理**: 模型偶尔会添加"翻译："等前缀，需要后处理
4. **上下文敏感**: 添加领域提示（如"昆虫学语境"）可改善特定术语准确性
