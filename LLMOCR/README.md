# LLMOCR — LLM 辅助词典图片 OCR + 结构化提取

LLMOCR 是 BioTransWorkers 项目内独立的数据处理子项目，专职利用多模态视觉语言模型（VLM）将昆虫形态学词典扫描页图片转化为结构化 JSON 词条数据。

## 数据流

```
AAFC_hymenoptera_of_the_world.pdf (源 PDF, 25页双栏词典)
    │
    └── Smallpdf 切分 → 26张 JPG 图片
            │
            ├── promote.txt (系统提示词, 定义提取规则)
            │
            ▼
        MiMo v2.5 API (小米多模态 VLM)
            │
            ▼
        aafc_glossary.json (结构化产物, 26页/198条词条)
```

## 输出格式

`aafc_glossary.json` — 扁平化词条列表 + 元数据：

```json
{
  "metadata": {
    "model": "mimo-v2.5",
    "total_pages": 26,
    "success_pages": 26,
    "total_entries": 198
  },
  "failed_pages": {},
  "entries": [
    {
      "term": "abdomen",
      "variants": "adj., abdominal",
      "definition": "The principal posterior division of the body...",
      "has_figure": true,
      "figure_bbox_approx": [0.14, 0.52, 0.50, 0.77],
      "column": "left",
      "reading_order": 1,
      "source_page": "AAFC_hymenoptera_of_the_world [44-69]-images-0.jpg"
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `term` | string | 词头原文，仅主词形 |
| `variants` | string | 圆括号内的变体说明（pl./adj.等），无则为空串 |
| `definition` | string | 定义正文，逐字忠实原文；跨页截断标 `[TRUNCATED]` |
| `has_figure` | bool | 是否配有线条插图 |
| `figure_bbox_approx` | [float×4] \| null | 插图边界框，**0.0~1.0 比例坐标**（x/w, y/h） |
| `column` | "left" \| "right" | 所属栏位 |
| `reading_order` | int | 页内阅读序号（左栏→右栏，上→下） |
| `source_page` | string | 来源图片文件名（脚本自动注入） |

## 提示词工程

系统提示词 `promote.txt` (~1.2KB) 定义：

| 部分 | 内容 |
|------|------|
| 任务 | 昆虫学词典扫描页 → 结构化词条提取 |
| 版面规则 | 双栏、加粗词头+圆括号变体、线描插图 |
| 输出格式 | 严格 JSON 数组，字段规范含 bbox 比例坐标 |
| 约束 (6条) | 原文保真、复合词条拆分、`[TRUNCATED]` 标记、bbox 比例制、禁止非 JSON 输出 |

### 插图坐标设计：归一化比例

**为什么不直接用像素？** VLM 内部会将图片缩放到固定处理分辨率（~1024px 长边），模型给出的像素坐标是**内部画布坐标**，非原图像素。原图 2550×3299，模型输出 x 范围仅 142~903，缩放比不一致。

**解决方案**：提示词要求输出 **0.0~1.0 比例值**，与分辨率无关：

```python
# 拿到比例坐标后，乘以原图宽高还原像素
from PIL import Image
img = Image.open("page.jpg")          # e.g. 2550×3299
w, h = img.size
bbox = [0.14, 0.52, 0.50, 0.77]      # 模型输出
x1, y1 = int(bbox[0] * w), int(bbox[1] * h)
x2, y2 = int(bbox[2] * w), int(bbox[3] * h)
# → 像素 (357, 1715) ~ (1275, 2540)，可直接用于 OpenCV 裁剪
```

## API — MiMo v2.5

| 项目 | 值 |
|------|-----|
| Base URL | `https://api.xiaomimimo.com/v1` |
| 协议 | OpenAI 兼容（Chat Completions） |
| 模型 | `mimo-v2.5`（多模态视觉语言模型） |
| Auth Header | `api-key: sk-xxxxx`（非 `Authorization: Bearer`） |
| API Key 存放 | 项目根 `.dev.vars` 第21-23行 |
| 产品页 | https://mimo.xiaomi.com |

### 请求参数

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `temperature` | `0.01` | OCR/结构化提取需极低温度，防止编造 |
| `max_completion_tokens` | `8192` | 单页词条多时需足够大（用此名，非 `max_tokens`） |
| `thinking` | `{"type": "disabled"}` | **必须关闭**，MiMo 默认开启 reasoning 会吞掉所有输出 token |

### 图片传入方式

**本地 Base64**（当前方案）：

```python
import base64
with open("page.jpg", "rb") as f:
    img_b64 = base64.b64encode(f.read()).decode("utf-8")

# 请求体中
{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
```

URL 方式也可用，但本地 base64 免去额外图片托管。大图 (>20MB) 建议改用 URL。

### 图片 Token

图片按视觉编码器计费，计入 `prompt_tokens`。`usage.prompt_tokens_details.image_tokens` 显示图片 token 数。实测 872KB JPG → ~8058 image tokens。

### 响应结构

```json
{
  "choices": [{"message": {"content": "```json\\n[...]\\n```"}}],
  "usage": {
    "prompt_tokens": 8694,
    "completion_tokens": 578,
    "completion_tokens_details": {"reasoning_tokens": 0},
    "prompt_tokens_details": {"image_tokens": 8058, "cached_tokens": 8640}
  }
}
```

## 实测结果

| 指标 | 值 |
|------|-----|
| 处理页数 | 26 / 26 |
| 总词条数 | **198** |
| 成功率 | 100%（含1页重试） |
| 左右栏分布 | 左 98 / 右 100 |
| 含配图词条 | 154 (78%) |
| 无配图词条 | 44 (22%) |
| 所有 bbox | 均在 0.0~1.0 比例范围 |
| 单页耗时 | 5~20s |
| 总耗时 | 4.4 分钟 |

## 文件清单

### 输入

| 文件 | 说明 |
|------|------|
| `AAFC_hymenoptera_of_the_world [44-69].pdf` | 源 PDF：膜翅目形态学词典，25页 |
| `smallpdf-convert-20260714-232145/` | PDF 切片产物：26 张 JPG（~700KB/张） |
| `promote.txt` | 系统提示词，1.2KB，定义版面规则+输出格式+约束 |
| `.dev.vars` (项目根) | API Key 配置 |

### 输出

| 文件 | 说明 | 大小 |
|------|------|------|
| `aafc_glossary.json` | 最终产物：198条结构化词条 | ~89KB |
| `aafc_checkpoint.json` | 断点续传中间状态（运行后产生） | — |

### 脚本

| 文件 | 说明 |
|------|------|
| `run_ocr_batch.py` | **主力脚本**：遍历全部图片，并发调用 MiMo，断点续传 + 自动校验 + 汇总输出 |
| `promote.txt` | 系统提示词（同时是配置文件） |

## 使用方式

```bash
cd LLMOCR
python run_ocr_batch.py
```

### 断点续传

中断后直接重新运行，脚本自动读取 `aafc_checkpoint.json`，跳过已处理页面，仅处理剩余。

### 重试失败页

从 `aafc_checkpoint.json` 的 `failed` 字段中删除对应条目，再运行即可重新处理。

## 与 LLMTRANS 的关系

LLMTRANS 和 LLMOCR 是 BioTransWorkers 的两个独立 LLM 数据处理子项目：

| 维度 | LLMTRANS | LLMOCR |
|------|----------|--------|
| 输入 | HAO 文本术语表 (~2600条) | 词典扫描页图片 (26张) |
| 模型 | DeepSeek V4 Pro (纯文本) | MiMo v2.5 (多模态) |
| 任务 | 术语翻译 + 音标 + 变体 | 图片 OCR + 结构化提取 |
| 输出 | `hao_dsv4.txt` (6行块格式) | `aafc_glossary.json` (JSON 数组) |
| 技术共性 | 断点续传、低温采样、thinking 关闭、prompt 工程 | 同模式 |

两者的输出产物最终均可导入 glossary/ → KV → BioTransWorkers 术语匹配引擎。

## 常见问题

### Q: 返回 content 为空？
**A**: 检查是否关闭了 thinking。`"thinking": {"type": "disabled"}` 必须设置。

### Q: max_tokens vs max_completion_tokens？
**A**: MiMo 使用 `max_completion_tokens`（与 OpenAI 新版 API 一致）。`max_tokens` 虽兼容但建议用前者。

### Q: bbox 坐标如何用于 OpenCV 裁剪？
**A**: 见上文"插图坐标设计"章节的比例→像素转换代码。

### Q: 模型返回非标准 JSON（带 markdown 包装）？
**A**: 脚本已内置 `parse_json_content()` 自动剥离 \`\`\`json ... \`\`\` 包装。
