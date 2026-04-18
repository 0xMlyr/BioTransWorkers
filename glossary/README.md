# 数据集

### 工程测试词汇
metadata:[source:engine_test, ver:1.0.0, date:20260419]
//工程测试词汇
null

### HAO
metadata:[source:hao_core_2023, ver:1.0.0, date:20260419]
//HAO核心词汇
Hymenoptera Anatomy Ontology
The official source of OWL version of the HAO.
https://github.com/hymao/hao

### HAO_INFLECT
metadata:[source:hao_inflect, ver:1.0.0, date:20260419]
//HAO核心词汇的单复数、形容词化等变形词
null

### MY_TERM
metadata:[source:my_term_202604, ver:1.0.0, date:20260419]
//自定义词汇表
my_glossary.json
my_glossary.txt

### GROUP_NAME
metadata:[source:group_name_202604, ver:1.0.0, date:20260419]
//膜翅目系统发生分类学术语分组名称
null


# 数据集格式

### Local Glossary Structure:
[
    {
        "key": "英文原词",
        "value": {
            "data": [
                {
                    "metadata": {
                        "source": "<source>",
                        "ver": "<ver>",
                        "date": "<date>"
                    },
                    "detailed": {...}
                }
            ]
        }
    }
]

### Cloudflare KV Structure:
key = 英文原词
value = 
    {
        data: [
            {
                metadata: {
                    source: "<source>",
                    ver: "<ver>",
                    date: "<date>"
                }
                detailed: {
                    ...
                }
            },
            {
                metadata: {
                    source: "<source>",
                    ver: "<ver>",
                    date: "<date>"
                }
                detailed: {
                    ...
                }
            }
        ]
    }


# 导入

## 导入脚本

脚本位置：`glossary/import_to_kv.py`

### 两种导入模式

| 模式 | 参数 | API 调用 | 适用场景 | 行为 |
|------|------|---------|---------|------|
| **批量模式** | `--bulk` / `-b` | **3 次** | 首次导入、覆盖写入 | 直接覆盖云端数据 |
| **合并模式** | （默认） | N 次 | 追加新数据集 | 读取-合并-写回 |

### 使用示例

```bash
# 1. 首次导入 HAO（批量模式，覆盖写入）
python glossary/import_to_kv.py glossary/hao_core/hao_for_kv.json --bulk

# 2. 追加 MY_TERM（合并模式，智能合并）
python glossary/import_to_kv.py glossary/my_trem_202604/my_term_for_kv.json

# 3. 重试失败的 key
python glossary/import_to_kv.py glossary/hao_core/hao_for_kv.json --retry-failed failed_keys.txt
```

### 合并模式逻辑

对于与云端已有 key 重复的术语（如 `abdomen` 同时存在于 HAO 和 MY_TERM）：

1. **读取**：从 KV 拉取现有 value
2. **合并**：将本地 data 并入现有 data 数组（按 `source` 去重，同 source 不重复写入）
3. **写回**：将合并后的 value 写回 KV

合并后的数据结构示例：
```json
{
  "key": "abdomen",
  "value": {
    "data": [
      {
        "metadata": {"source": "hao_core_2023", "ver": "1.0.0", "date": "20260419"},
        "detailed": {"id": "HAO:0000015", "name": "abdomen", "def": "..."}
      },
      {
        "metadata": {"source": "my_term_202604", "ver": "1.0.0", "date": "20260419"},
        "detailed": {"original": "abdomen", "translation": "腹部"}
      }
    ]
  }
}
```

### 批量模式逻辑

适用于首次导入或需要完全覆盖的场景：

1. **去重**：本地文件可能存在同名 key（如 HAO 的有效+废弃术语），自动合并为单个 key
2. **分批**：每批最多 1000 条，减少 API 调用次数
3. **覆盖**：直接写入云端，不读取现有数据

### 注意事项

1. **API 限额**：Cloudflare KV Free 计划每天 1,000 次写入
   - 批量模式：3 次调用导入 2,537 条（推荐首次使用）
   - 合并模式：每条 1 次调用（适合追加）

2. **重复 source 处理**：同一 source 的数据不会重复写入，避免数据膨胀

3. **日志记录**：每次导入生成日志文件 `import_log_YYYYMMDDHHMMSS.txt`，记录详细操作

4. **失败重试**：失败的 key 会保存到 `failed_keys_YYYYMMDDHHMMSS.txt`，可用 `--retry-failed` 重试