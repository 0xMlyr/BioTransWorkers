# LLMTRANS — LLM 辅助 HAO 术语翻译

LLMTRANS 是 BioTransWorkers 项目内独立的数据处理子项目，专职利用 LLM 将 Hymenoptera Anatomy Ontology (HAO) 的 ~2600 条英文昆虫形态学术语翻译为汉语，同时生成国际音标（IPA）和拉丁/希腊语形态变体。

## 数据流

```
hao.txt (源文件, 2596条, ZH/INFLECT/PHONETC为空)
    │
    ├── promote.txt (系统提示词)
    │
    ▼
LLM API (DeepSeek V4 Pro)
    │
    ▼
hao_dsv4.txt (翻译产物, 2596条全量完成)
    │
    ▼
导入 glossary/ → KV → BioTransWorkers 术语匹配引擎
```

## 尝试历程

### Round 1 — GLM5 (失败)

- **模型**: `cqtbi-glm5`
- **API**: `https://aidmx.cqtbi.edu.cn/v1`（第三方代理，QPS=55/min）
- **脚本**: `translate_batch.py`（硬编码翻译前50条）
- **结果**: `hao_glm5.txt` — 仅完成 **50/2596** (2%)

### Round 2 — DeepSeek V3 (失败)

- **模型**: `cqtbi-deepseek-v3-2`
- **API**: 同上第三方代理
- **脚本**: `translate_batch_v2.py`（从第300行起翻200条）
- **结果**: `hao_dkv3.txt` — 仅完成 **250/2596** (10%)

**失败根因**：旧脚本硬编码批次上限，需反复手动调整起始行；第三方代理 QPS 限制严苛，中途易中断。

### Round 3 — DeepSeek V4 Pro (成功)

- **模型**: `deepseek-v4-pro`
- **API**: `https://api.deepseek.com/v1`（杭州 DeepSeek 官方）
- **Token**: 配置于项目根 `.dev.vars` 第19行
- **脚本**: `translate_all_dsv4.py`（全量翻译 + 断点续传 + 实时日志）
- **结果**: `hao_dsv4.txt` — **2596/2596 (100%)**

## 提示词工程

系统提示词 `promote.txt` (~7.7KB) 经过多轮优化，核心设计：

### 三级置信度标注体系

| 级别 | 标注方式 | 示例 |
|------|---------|------|
| **确定** | 直接输出汉语 | `ZH:并胸腹节` `ZH:上颚` |
| **存疑** | 半角括号 `()` 包裹 | `ZH:(并胸腹节腹侧中区)` `ZH:(左右扁平的)` |
| **无译** | 输出 `[待译]` | `ZH:[待译]` |

组合示例：`ZH:前基腹隆线|(中胸侧板前腹侧脊)`（确定+存疑混合）

### 提示词结构

| 部分 | 内容 |
|------|------|
| 角色定义 | 膜翅目分类学/形态学/解剖学翻译专家 |
| 作用域限定 | 昆虫学语境，与人体解剖学术语严格区分 |
| 输入输出格式 | `NAME` / `DEF` 入，`NAME` / `ZH` / `PHONETIC` / `INFLECT` 出 |
| 三级置信度体系 | 确定（无括号）、存疑（括号）、无译（[待译]） |
| 变形规则 | 拉丁/希腊语单复数、形容词化、部位小称、方位复合词 |
| 特殊处理规则 | 肌肉术语、骨片/骨板、翅脉、无标准译词 |
| 输出示例 | 12组完整 I/O 示例覆盖所有置信度级别 |
| 汉语翻译对照表 | ~130条自整理权威译词（来自 `my_glossary.txt`） |

## API 关键技术点

| 项目 | 值 |
|------|-----|
| 端点 | `https://api.deepseek.com/v1/chat/completions` |
| 模型 | `deepseek-v4-pro` |
| thinking | **必须 `disabled`**（默认开启会挤占输出 token） |
| temperature | 0.01 |
| top_p | 0.1 |
| max_tokens | 250 |
| 并发限制 | 500 (账号级) |
| KVCache | 自动开启，第2次请求起系统提示词命中缓存 |

### 费用估算

| 阶段 | 输入价格 | 说明 |
|------|---------|------|
| 首次请求 | $0.435 / 1M tokens | cache miss，system prompt 全量计费 |
| 后续请求 | $0.003625 / 1M tokens | cache hit，仅术语内容计费 (~50x 便宜) |
| 输出 | $0.87 / 1M tokens | 每条约 40-80 tokens |

2596 条术语实际消耗约 7M input tokens + 0.15M output tokens ≈ $0.13。

## 翻译结果统计

| 级别 | 数量 | 占比 |
|------|------|------|
| **确定** | 1069 | 41% |
| **存疑** | 894 | 34% |
| **确定+存疑** | 483 | 19% |
| **无译** | 150 | 6% |

- 总耗时: 106 分钟 (1.8 h)
- 速率: 24.4 terms/min
- 成功率: 100% (2596/2596, 0 failures)
- 94% 的术语获得了可用的汉语翻译

## 文件清单

### 输入

| 文件 | 说明 |
|------|------|
| `hao.txt` | 源数据：2596条HAO术语，ZH/INFLECT/PHONETC字段为空，384KB |
| `promote.txt` | 系统提示词，7.7KB，11组I/O示例 + ~130条权威译词对照表 |
| `.dev.vars` (项目根) | API Key 配置 |

### 输出

| 文件 | 模型 | 完成度 | 大小 |
|------|------|--------|------|
| `hao_dsv4.txt` | DeepSeek V4 Pro | **2596/2596 (100%)** | 640KB |
| `hao_dkv3.txt` | DeepSeek V3 | 250/2596 (10%) | 417KB |
| `hao_glm5.txt` | GLM5 | 50/2596 (2%) | 404KB |
| `hao_dsv4_test.txt` | V4 Pro (测试) | 50/2596 | 403KB |

### 脚本

| 文件 | 说明 |
|------|------|
| `translate_all_dsv4.py` | **主力脚本**：全量翻译 + 断点续传 + 实时日志 + 置信度统计 |
| `translate_dsv4.py` | 小批量测试脚本（前50条） |
| `test_dsv4.py` | API 连通性与术语翻译测试 |
| `translate_batch.py` | Round 1 脚本（GLM5 / DKV3，已废弃） |
| `translate_batch_v2.py` | Round 2 脚本（DKV3 续传，已废弃） |

## 使用方式

```bash
# 全量翻译（支持断点续传 — 自动跳过已翻译的术语）
cd LLMTRANS
python translate_all_dsv4.py

# 调整批次大小
# 编辑 translate_all_dsv4.py: SAVE_EVERY = 10
```

翻译结果写入 `hao_dsv4.txt`，格式与源文件 `hao.txt` 一致（6行块：NAME / DEF / ZH / INFLECT / PHONETC / 空行），可直接用于后续 KV 导入。

## 后续步骤

1. 人工审核 `hao_dsv4.txt` 中存疑和无译的术语
2. 将审核通过的译词合并到 cloudflare KV
3. 重建 AC 自动机：`cd glossary/automaton && python build_ac.py`
4. 部署到 Cloudflare KV
