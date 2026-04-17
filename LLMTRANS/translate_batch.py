#!/usr/bin/env python3
"""
HAO术语批量翻译脚本 - DeepSeek V3
从hao.txt读取，翻译后写入hao_dkv3.txt
"""

import os
import sys
import time
import requests

# ==================== 配置 ====================
API_URL = "https://aidmx.cqtbi.edu.cn/v1/chat/completions"
API_KEY = "sk-g4A9IFICIxhvLz87Dl7ZmceRhlBlio5p_L1FPA4VNtY"
MODEL = "cqtbi-deepseek-v3-2"  # DKV3模型

# 路径配置
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(SCRIPT_DIR, "promote.txt")
SOURCE_FILE = os.path.join(SCRIPT_DIR, "hao.txt")
TARGET_FILE = os.path.join(SCRIPT_DIR, "hao_dkv3.txt")  # DKV3输出文件

# QPS控制: 55/分钟 = 1.09秒/请求，取1.2秒安全间隔
MIN_INTERVAL = 1.2

# ==================== 读取文件 ====================
def read_prompt():
    """读取系统提示词"""
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip()

def read_source_terms(count=50):
    """
    从hao.txt读取前N个术语
    每个术语占6行: NAME, DEF, ZH, INFLECT, PHONETC, 空行
    返回: [(term_index, name, def, start_line, end_line), ...]
    """
    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    terms = []
    i = 0
    term_count = 0
    
    while i < len(lines) and term_count < count:
        line = lines[i].strip()
        
        if line.startswith("NAME:"):
            start_line = i
            name = line[5:]  # 去掉"NAME:"
            
            # 读取DEF
            def_line = ""
            if i + 1 < len(lines):
                def_line = lines[i + 1].strip()
                if def_line.startswith("DEF:"):
                    def_line = def_line[4:]
            
            # 计算这个术语块的结束位置（找到下一个NAME或空行后的NAME）
            end_line = start_line + 6  # 默认6行一个块
            for j in range(start_line + 1, min(start_line + 7, len(lines))):
                if j < len(lines) and lines[j].strip() == "":
                    end_line = j
                    break
            
            terms.append({
                'index': term_count,
                'name': name,
                'definition': def_line,
                'start_line': start_line,
                'end_line': end_line
            })
            term_count += 1
            i = end_line + 1
        else:
            i += 1
    
    return terms

def read_target_file():
    """读取目标文件的所有行"""
    if not os.path.exists(TARGET_FILE):
        # 如果目标文件不存在，复制源文件
        with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        with open(TARGET_FILE, 'w', encoding='utf-8') as f:
            f.write(content)
    
    with open(TARGET_FILE, 'r', encoding='utf-8') as f:
        return f.readlines()

def write_target_file(lines):
    """写入目标文件"""
    with open(TARGET_FILE, 'w', encoding='utf-8') as f:
        f.writelines(lines)

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
            print(f"    [QPS] 等待 {sleep_time:.2f} 秒...")
            time.sleep(sleep_time)
        self.last_request_time = time.time()
    
    def translate(self, name, definition):
        """
        翻译单个术语
        返回: (zh, phonetic, inflect) 或 None
        """
        self._wait_for_qps()
        
        # 构建用户输入
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
            print(f"    [API] 请求: {name[:50]}...")
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
                    continue  # 跳过NAME行
                elif line.startswith("ZH:"):
                    zh = line[3:]
                elif line.startswith("PHONETIC:"):
                    phonetic = line[9:]
                elif line.startswith("INFLECT:"):
                    inflect = line[8:]
            
            return {
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
    print("=" * 60)
    print("HAO术语批量翻译 - DeepSeek V3")
    print("=" * 60)
    
    # 读取前50个术语
    print(f"\n[1/4] 读取源文件: {SOURCE_FILE}")
    terms = read_source_terms(50)
    print(f"       找到 {len(terms)} 个术语")
    
    # 读取目标文件
    print(f"\n[2/4] 读取目标文件: {TARGET_FILE}")
    target_lines = read_target_file()
    print(f"       目标文件共 {len(target_lines)} 行")
    
    # 初始化翻译器
    print(f"\n[3/4] 初始化LLM翻译器")
    print(f"       模型: {MODEL}")
    print(f"       QPS限制: {MIN_INTERVAL}秒/请求")
    translator = LLMTranslator(API_KEY, API_URL, MODEL)
    
    # 批量翻译
    print(f"\n[4/4] 开始翻译 {len(terms)} 个术语...")
    print("-" * 60)
    
    success_count = 0
    fail_count = 0
    
    for i, term in enumerate(terms):
        print(f"\n[{i+1}/{len(terms)}] {term['name'][:60]}")
        
        result = translator.translate(term['name'], term['definition'])
        
        if result:
            success_count += 1
            print(f"    [OK] ZH: {result['zh'][:40]}")
            print(f"       PHONETIC: {result['phonetic'][:30]}")
            print(f"       INFLECT: {result['inflect'][:30]}")
            
            # 更新目标文件的对应行
            # 术语在目标文件中的位置：term['start_line'] 到 term['end_line']
            # 需要更新 ZH, PHONETC, INFLECT 三行
            
            start = term['start_line']
            # ZH在第2行（相对）= start + 2
            # PHONETC在第4行（相对）= start + 4
            # INFLECT在第3行（相对）= start + 3
            
            if start + 2 < len(target_lines):
                target_lines[start + 2] = f"ZH:{result['zh']}\n"
            if start + 3 < len(target_lines):
                target_lines[start + 3] = f"INFLECT:{result['inflect']}\n"
            if start + 4 < len(target_lines):
                # 注意：原文件是PHONETC（拼写错误），保持一致
                target_lines[start + 4] = f"PHONETC:{result['phonetic']}\n"
        else:
            fail_count += 1
            print(f"    [FAIL] 翻译失败，跳过")
    
    # 保存结果
    print("\n" + "=" * 60)
    print("保存结果...")
    write_target_file(target_lines)
    
    print(f"\n完成！成功: {success_count}, 失败: {fail_count}")
    print(f"结果已写入: {TARGET_FILE}")

if __name__ == "__main__":
    main()
