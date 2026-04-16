hao
Hymenoptera Anatomy Ontology

The official source of OWL version of the HAO.

https://github.com/hymao/hao

# HAO 数据转换记录

## 源文件信息

- **名称**: Hymenoptera Anatomy Ontology (HAO)
- **官方仓库**: https://github.com/hymao/hao
- **原始文件**: `hao.obo` (OBO 1.2 格式)
- **总长度**: 20,677 行

## 转换统计

| 指标 | 数值 |
|------|------|
| 总条目数 | **2,596** |
| 有效条目 | **2,513** |
| 废弃条目 | **83** |

## 转换操作

### 脚本文件
- `convert-hao.js` - OBO 到 JSON 的转换脚本

### 执行命令
```bash
node glossary/convert-hao.js
```

### 输出文件
- `hao.json` - 转换后的 JSON 数据（85,429 行）

## JSON 数据结构

每个术语条目包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | HAO 唯一标识符（如 `HAO:0000000`） |
| `name` | string | 英文术语名称 |
| `def` | string | 定义描述（纯文本） |
| `def_refs` | array | 定义引用来源 |
| `synonyms` | array | 同义词数组（含 `name` 和 `refs`） |
| `is_a` | array | 父类继承关系（含 `id` 和 `name`） |
| `relationships` | array | 关联关系（含 `type`, `target_id`, `target_name`） |
| `xrefs` | array | 外部本体引用 |
| `is_obsolete` | boolean | 是否废弃 |
| `comment` | string | 注释 |
| `chinese_name` | string | **汉译名称（预留，待填充）** |
| `phonetic` | string | **音标（预留，待填充）** |

## 待办事项

- [ ] 填充 `chinese_name` 字段（中文翻译）
- [ ] 填充 `phonetic` 字段（音标）
- [ ] 编写 KV 导入脚本
- [ ] 写入 Cloudflare KV

---

*生成时间: 2026-04-16*