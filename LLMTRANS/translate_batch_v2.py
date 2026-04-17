#!/usr/bin/env python3
"""
HAO术语批量翻译脚本 V2 - 按名称匹配写入，每10条保存一次
从指定行开始，向后翻译N个术语
"""

import os
import time
import re
import requests

# ==================== 配置 ====================
API_URL = "https://aidmx.cqtbi.edu.cn/v1/chat/completions"
API_KEY = "sk-g4A9IFICIxhvLz87Dl7ZmceRhlBlio5p_L1FPA4VNtY"
MODEL = "cqtbi-deepseek-v3-2"

# 路径配置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(SCRIPT_DIR, "promote.txt")
SOURCE_FILE = os.path.join(SCRIPT_DIR, "hao.txt")
TARGET_FILE = os.path.join(SCRIPT_DIR, "hao_dkv3.txt")

# QPS控制
MIN_INTERVAL = 1.2

# 任务参数
START_LINE = 300  # 从第300行开始（1-based）
BATCH_TOTAL = 200  # 总共翻译200个术语
SAVE_EVERY = 10   # 每10条保存一次

# ==================== 读取文件 ====================
def read_prompt():
    """读取系统提示词"""
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip()

def parse_terms_from_line(start_line, count):
    """
    从指定行开始解析术语
    返回: [{name, def, line_num}, ...]
    """
    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    terms = []
    i = start_line - 1  # 转为0-based索引
    term_count = 0
    
    while i < len(lines) and term_count < count:
        line = lines[i].strip()
        
        if line.startswith("NAME:"):
            name = line[5:].strip()
            def_text = ""
            
            # 读取DEF（下一行）
            if i + 1 < len(lines):
                def_line = lines[i + 1].strip()
                if def_line.startswith("DEF:"):
                    def_text = def_line[4:].strip()
            
            terms.append({
                'name': name,
                'definition': def_text,
                'line_num': i + 1  # 1-based行号，用于参考
            })
            term_count += 1
            i += 6  # 跳过当前术语的6行（NAME,DEF,ZH,INFLECT,PHONETC,空行）
        else:
            i += 1
    
    return terms

def load_target_file_as_dict():
    """
    将目标文件加载为字典: {name: {zh, inflect, phonetc, line_indices}}
    这样可以按名称查找并更新
    """
    if not os.path.exists(TARGET_FILE):
        # 复制源文件作为基础
        with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(TARGET_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
    
    with open(TARGET_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    term_dict = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("NAME:"):
            name = line[5:].strip()
            # 记录该术语占据的行索引
            term_dict[name] = {
                'name_line': i,
                'zh_line': i + 2 if i + 2 < len(lines) else None,
                'inflect_line': i + 3 if i + 3 < len(lines) else None,
                'phonetc_line': i + 4 if i + 4 < len(lines) else None,
            }
            i += 6  # 跳到下一个术语块
        else:
            i += 1
    
    return term_dict, lines

def save_translations_to_file(translation_results, term_dict, all_lines):
    """
    将翻译结果写入文件
    translation_results: [{name, zh, phonetic, inflect}, ...]
    """
    modified = False
    
    for result in translation_results:
        name = result['name']
        if name not in term_dict:
            print(f"    [WARN] 未找到术语: {name[:50]}")
            continue
        
        info = term_dict[name]
        
        # 更新ZH行
        if info['zh_line'] is not None:
            all_lines[info['zh_line']] = f"ZH:{result['zh']}\n"
        
        # 更新INFLECT行
        if info['inflect_line'] is not None:
            all_lines[info['inflect_line']] = f"INFLECT:{result['inflect']}\n"
        
        # 更新PHONETC行（注意原文件拼写是PHONETC不是PHONETIC）
        if info['phonetc_line'] is not None:
            all_lines[info['phonetc_line']] = f"PHONETC:{result['phonetic']}\n"
        
        modified = True
    
    if modified:
        with open(TARGET_FILE, 'w', encoding='utf-8') as f:
            f.writelines(all_lines)
        return True
    return False

# ==================== LLM API ====================
class LLMTranslator:
    def __init__(self, api_key, api_url, model):
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self.last_request_time = 0
        self.system_prompt = read_prompt()
    
    def _wait_for_qps(self):
        """等待以符合QPS限制"""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < MIN_INTERVAL:
            sleep_time = MIN_INTERVAL - elapsed
            time.sleep(sleep_time)
        self.last_request_time = time.time()
    
    def translate(self, name, definition):
        """翻译单个术语"""
        self._wait_for_qps()
        
        user_content = f"NAME:{name}\nDEF:{definition}"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.01,
            "top_p": 0.1,
            "max_tokens": 100,
            "stream": False
        }
        
        try:
            resp = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=60
            )
            resp.raise_for_status()
            
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            
            # 解析返回的4行格式
            lines = [l.strip() for l in content.split('\n') if l.strip()]
            
            zh = ""
            phonetic = ""
            inflect = ""
            
            for line in lines:
                if line.startswith("NAME:"):
                    continue
                elif line.startswith("ZH:"):
                    zh = line[3:]
                elif line.startswith("PHONETIC:"):
                    phonetic = line[9:]
                elif line.startswith("INFLECT:"):
                    inflect = line[8:]
            
            return {
                'name': name,
                'zh': zh,
                'phonetic': phonetic,
                'inflect': inflect,
                'raw_response': content
            }
            
        except Exception as e:
            print(f"    [ERROR] 请求失败: {e}")
            return None

# ==================== 主流程 ====================
def main():
    print("=" * 70)
    print(f"HAO术语批量翻译 - DKV3 (从第{START_LINE}行起，共{BATCH_TOTAL}词)")
    print("=" * 70)
    
    # 解析术语
    print(f"\n[1/4] 从hao.txt第{START_LINE}行开始解析...")
    terms = parse_terms_from_line(START_LINE, BATCH_TOTAL)
    print(f"       找到 {len(terms)} 个术语")
    print(f"       首词: {terms[0]['name'][:50] if terms else 'N/A'}")
    print(f"       末词: {terms[-1]['name'][:50] if terms else 'N/A'}")
    
    # 加载目标文件
    print(f"\n[2/4] 加载目标文件字典...")
    term_dict, all_lines = load_target_file_as_dict()
    print(f"       目标文件共 {len(all_lines)} 行，{len(term_dict)} 个术语")
    
    # 初始化翻译器
    print(f"\n[3/4] 初始化LLM翻译器 (模型: {MODEL})")
    translator = LLMTranslator(API_KEY, API_URL, MODEL)
    
    # 批量翻译，每SAVE_EVERY条保存一次
    print(f"\n[4/4] 开始翻译 (每{SAVE_EVERY}条保存一次)...")
    print("-" * 70)
    
    success_count = 0
    fail_count = 0
    batch_results = []
    
    for i, term in enumerate(terms):
        batch_num = (i // SAVE_EVERY) + 1
        item_num = (i % SAVE_EVERY) + 1
        
        print(f"\n[{batch_num}/{((len(terms)-1)//SAVE_EVERY)+1}][{item_num}/{SAVE_EVERY}] {term['name'][:60]}")
        
        result = translator.translate(term['name'], term['definition'])
        
        if result:
            success_count += 1
            print(f"    [OK] ZH: {result['zh'][:40]}")
            batch_results.append(result)
        else:
            fail_count += 1
            print(f"    [FAIL] 翻译失败")
        
        # 每SAVE_EVERY条或最后一条时保存
        if (i + 1) % SAVE_EVERY == 0 or i == len(terms) - 1:
            if batch_results:
                print(f"\n    [SAVE] 保存 {len(batch_results)} 条结果...")
                save_translations_to_file(batch_results, term_dict, all_lines)
                batch_results = []  # 清空已保存的结果
                print(f"    [OK] 已写入 {TARGET_FILE}")
    
    print("\n" + "=" * 70)
    print("完成！")
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  总计: {len(terms)}")
    print(f"  输出: {TARGET_FILE}")

if __name__ == "__main__":
    main()
