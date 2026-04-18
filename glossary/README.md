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