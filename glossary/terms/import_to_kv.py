#!/usr/bin/env python3
"""
通用 KV 导入脚本
将本地 _for_kv.json 文件无损导入 Cloudflare KV，支持多数据源合并

用法:
    python import_to_kv.py <path_to_for_kv.json> [--retry-failed <failed_keys_file>]

示例:
    python import_to_kv.py hao_core/hao_for_kv.json
    python import_to_kv.py my_trem_202604/my_term_for_kv.json --retry-failed failed_keys_20260419.txt
"""

import json
import sys
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Set
import requests


def setup_logging(log_file: Path):
    """设置日志：同时输出到控制台和文件"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 清除现有处理器
    logger.handlers = []
    
    # 格式化
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    
    # 控制台处理器（实时显示）
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)
    
    # 文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


class KVImporter:
    """KV 导入器，支持读取-合并-回写流程"""
    
    def __init__(self, account_id: str, api_token: str, namespace_id: str, logger: Optional[logging.Logger] = None):
        self.account_id = account_id
        self.api_token = api_token
        self.namespace_id = namespace_id
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/storage/kv/namespaces/{namespace_id}"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        self.failed_keys: List[str] = []
        self.success_count = 0
        self.merge_count = 0
        self.new_count = 0
        self.logger = logger or logging.getLogger()
        
    def load_local_data(self, json_path: Path) -> List[Dict[str, Any]]:
        """加载本地 _for_kv.json 文件"""
        self.logger.info(f"Loading local data from {json_path}...")
        with open(json_path, 'r', encoding='utf-8') as f:
            entries = json.load(f)
        self.logger.info(f"Loaded {len(entries)} entries")
        return entries
    
    def load_failed_keys(self, failed_file: Path) -> Set[str]:
        """加载之前失败的 key 列表"""
        if not failed_file.exists():
            return set()
        with open(failed_file, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())
    
    def get_kv_value(self, key: str) -> Optional[Dict]:
        """从 KV 获取指定 key 的值，不存在返回 None"""
        url = f"{self.base_url}/values/{key}"
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            if response.status_code == 404:
                return None
            elif response.status_code == 200:
                # KV 存储的是 JSON 字符串，需要解析
                text_value = response.text
                try:
                    return json.loads(text_value)
                except json.JSONDecodeError:
                    self.logger.warning(f"Existing value for '{key}' is not valid JSON")
                    return None
            else:
                self.logger.error(f"Error fetching '{key}': HTTP {response.status_code}")
                return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error fetching '{key}': {e}")
            return None
    
    def merge_data(self, existing_value: Optional[Dict], new_entry: Dict) -> Dict:
        """合并本地数据到现有 KV 数据"""
        new_value = new_entry['value']
        new_data = new_value['data'] if isinstance(new_value, dict) else new_value
        
        if existing_value is None:
            # Key 不存在，直接创建
            return {'data': new_data if isinstance(new_data, list) else [new_data]}
        
        # Key 存在，需要合并 data 数组
        existing_data = existing_value.get('data', [])
        if not isinstance(existing_data, list):
            existing_data = [existing_data]
        
        # 检查是否已有相同 source 的数据，避免重复
        new_sources = {item.get('metadata', {}).get('source') for item in new_data}
        filtered_existing = [
            item for item in existing_data 
            if item.get('metadata', {}).get('source') not in new_sources
        ]
        
        # 合并：保留现有（去除重复 source）+ 新增
        merged_data = filtered_existing + (new_data if isinstance(new_data, list) else [new_data])
        
        return {'data': merged_data}
    
    def put_kv_value(self, key: str, value: Dict) -> bool:
        """将值写入 KV，返回是否成功"""
        url = f"{self.base_url}/values/{key}"
        # KV 需要存储 JSON 字符串
        json_value = json.dumps(value, ensure_ascii=False)
        
        try:
            response = requests.put(
                url, 
                headers=self.headers, 
                data=json_value.encode('utf-8'),
                timeout=30
            )
            if response.status_code in (200, 201):
                return True
            else:
                self.logger.error(f"Error writing '{key}': HTTP {response.status_code} - {response.text[:100]}")
                return False
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error writing '{key}': {e}")
            return False
    
    def process_entry(self, entry: Dict[str, Any]) -> bool:
        """处理单个 entry，返回是否成功"""
        key = entry['key']
        
        # 1. 读取云端现有值
        self.logger.debug(f"Fetching existing value for '{key}'...")
        existing = self.get_kv_value(key)
        
        # 2. 合并数据
        merged_value = self.merge_data(existing, entry)
        
        # 统计
        if existing is None:
            self.new_count += 1
            action = "NEW"
        else:
            self.merge_count += 1
            action = "MERGE"
        
        # 3. 回写 KV
        self.logger.debug(f"Writing '{key}' to KV...")
        if self.put_kv_value(key, merged_value):
            self.success_count += 1
            self.logger.info(f"[{action}] {key} - OK")
            return True
        else:
            self.failed_keys.append(key)
            self.logger.error(f"[{action}] {key} - FAILED")
            return False
    
    def put_kv_bulk(self, entries: List[Dict]) -> bool:
        """批量写入 KV（适用于首次导入，节省 API 调用次数）"""
        url = f"{self.base_url}/bulk"
        
        # 构建批量数据
        bulk_data = []
        for entry in entries:
            key = entry['key']
            value = entry['value']
            # value 必须是字符串
            if isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False)
            bulk_data.append({
                "key": key,
                "value": value
            })
        
        try:
            response = requests.put(
                url,
                headers=self.headers,
                json=bulk_data,
                timeout=60
            )
            if response.status_code in (200, 201):
                self.success_count += len(entries)
                self.new_count += len(entries)
                self.logger.info(f"BULK WRITE: {len(entries)} entries - OK")
                return True
            else:
                self.logger.error(f"BULK WRITE FAILED: HTTP {response.status_code} - {response.text[:200]}")
                # 记录所有 key 为失败
                for entry in entries:
                    self.failed_keys.append(entry['key'])
                return False
        except requests.exceptions.RequestException as e:
            self.logger.error(f"BULK WRITE NETWORK ERROR: {e}")
            for entry in entries:
                self.failed_keys.append(entry['key'])
            return False
    
    def deduplicate_entries(self, entries: List[Dict]) -> List[Dict]:
        """合并本地重复的 key（如有效+废弃术语同名）"""
        key_map = {}  # key -> merged entry
        
        for entry in entries:
            key = entry['key']
            value = entry['value']
            
            if key not in key_map:
                key_map[key] = entry.copy()
            else:
                # 合并 data 数组
                existing_data = key_map[key]['value']['data']
                new_data = value['data'] if isinstance(value, dict) else json.loads(value)['data']
                
                # 获取已有和新数据的 source
                existing_sources = {item['metadata']['source'] for item in existing_data}
                
                for item in new_data:
                    if item['metadata']['source'] not in existing_sources:
                        existing_data.append(item)
                        existing_sources.add(item['metadata']['source'])
                
                self.logger.debug(f"Merged duplicate key '{key}' - now has {len(existing_data)} data items")
        
        result = list(key_map.values())
        if len(result) < len(entries):
            self.logger.info(f"Merged {len(entries) - len(result)} duplicate keys, {len(result)} unique keys remaining")
        return result
    
    def import_bulk(self, json_path: Path, batch_size: int = 1000):
        """批量导入模式（节省 API 调用次数）"""
        entries = self.load_local_data(json_path)
        
        # 合并本地重复 key
        entries = self.deduplicate_entries(entries)
        total = len(entries)
        
        self.logger.info(f"BULK MODE: Importing {total} entries in batches of {batch_size}")
        self.logger.info(f"Estimated API calls: {(total + batch_size - 1) // batch_size}")
        self.logger.info("-" * 60)
        
        # 分批处理
        for i in range(0, total, batch_size):
            batch = entries[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total + batch_size - 1) // batch_size
            
            self.logger.info(f"Batch {batch_num}/{total_batches}: {len(batch)} entries")
            
            if self.put_kv_bulk(batch):
                self.logger.info(f"  ✓ Batch {batch_num} complete")
            else:
                self.logger.error(f"  ✗ Batch {batch_num} failed - will retry individually")
                # 批量失败，回退到单条处理
                for entry in batch:
                    self.process_entry(entry)
            
            # 延迟避免 rate limit
            if i + batch_size < total:
                time.sleep(1)
        
        # 报告
        self.logger.info("=" * 50)
        self.logger.info("Bulk Import Summary")
        self.logger.info("=" * 50)
        self.logger.info(f"Total entries:    {total}")
        self.logger.info(f"Successful:       {self.success_count}")
        self.logger.info(f"Failed:           {len(self.failed_keys)}")
        self.logger.info("=" * 50)
        
        return len(self.failed_keys) == 0
    
    def import_data(self, json_path: Path, failed_keys_file: Optional[Path] = None, 
                   retry_failed: Optional[Path] = None, use_bulk: bool = False):
        """执行导入流程"""
        # 如果使用批量模式（适合首次导入或覆盖）
        if use_bulk and not retry_failed:
            return self.import_bulk(json_path)
        
        # 加载数据
        entries = self.load_local_data(json_path)
        
        # 如果指定了重试文件，只处理失败的 key
        if retry_failed:
            failed_set = self.load_failed_keys(retry_failed)
            entries = [e for e in entries if e['key'] in failed_set]
            self.logger.info(f"Retry mode: filtering to {len(entries)} previously failed keys")
        
        total = len(entries)
        self.logger.info(f"Starting import to KV namespace {self.namespace_id}")
        self.logger.info(f"Total entries to process: {total}")
        self.logger.info(f"Progress format: [current/total] [NEW/MERGE] key_name - status")
        self.logger.info("-" * 60)
        
        # 逐条处理
        for i, entry in enumerate(entries, 1):
            key = entry['key']
            
            # 记录进度（每100条输出一次摘要）
            if i % 100 == 0 or i == total:
                progress_pct = (i / total) * 100
                self.logger.info(f"PROGRESS: [{i}/{total}] ({progress_pct:.1f}%) - {self.success_count} success, {len(self.failed_keys)} failed")
            
            success = self.process_entry(entry)
            
            if not success:
                self.logger.warning(f"[{i}/{total}] {key} - FAILED (will retry later)")
            
            # 短暂延迟避免 rate limit
            if i < total:
                time.sleep(0.1)
        
        # 保存失败的 key
        if self.failed_keys and failed_keys_file:
            with open(failed_keys_file, 'w', encoding='utf-8') as f:
                for key in self.failed_keys:
                    f.write(f"{key}\n")
            self.logger.info(f"Failed keys saved to: {failed_keys_file}")
        
        # 报告
        self.logger.info("=" * 50)
        self.logger.info("Import Summary")
        self.logger.info("=" * 50)
        self.logger.info(f"Total processed:  {total}")
        self.logger.info(f"Successful:       {self.success_count}")
        self.logger.info(f"Failed:           {len(self.failed_keys)}")
        self.logger.info(f"  - New keys:     {self.new_count}")
        self.logger.info(f"  - Merged keys:  {self.merge_count}")
        self.logger.info("=" * 50)
        
        return len(self.failed_keys) == 0


def load_config_from_env():
    """从 .dev.vars 文件加载配置"""
    dev_vars_path = Path(__file__).parent.parent / '.dev.vars'
    
    if not dev_vars_path.exists():
        logging.error(f"Error: .dev.vars not found at {dev_vars_path}")
        sys.exit(1)
    
    config = {}
    with open(dev_vars_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                if key == 'CF_ACCOUNT_ID':
                    config['account_id'] = value
                elif key == 'CF_API_TOKEN':
                    config['api_token'] = value
    
    return config


def load_kv_namespace():
    """从 wrangler.jsonc 加载 KV namespace ID"""
    wrangler_path = Path(__file__).parent.parent / 'wrangler.jsonc'
    
    if not wrangler_path.exists():
        logging.error(f"Error: wrangler.jsonc not found at {wrangler_path}")
        sys.exit(1)
    
    import re
    content = wrangler_path.read_text(encoding='utf-8')
    
    # 查找 id 字段（支持 JSONC 注释）
    match = re.search(r'"id"\s*:\s*"([a-f0-9]+)"', content)
    if match:
        return match.group(1)
    
    logging.error("Error: Could not find KV namespace id in wrangler.jsonc")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Import local glossary data to Cloudflare KV',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 首次导入/覆盖：批量模式（3 次 API 调用）
  python import_to_kv.py hao_core/hao_for_kv.json --bulk
  
  # 增量导入：智能合并模式
  python import_to_kv.py my_trem_202604/my_term_for_kv.json
  
  # 重试失败的 key
  python import_to_kv.py hao_core/hao_for_kv.json --retry-failed failed_keys.txt
        """
    )
    parser.add_argument('json_file', help='Path to _for_kv.json file')
    parser.add_argument('--output-failed', '-o', 
                        help='File to save failed keys (default: failed_keys_<timestamp>.txt)')
    parser.add_argument('--retry-failed', '-r',
                        help='Retry keys from previous failed file')
    parser.add_argument('--bulk', '-b', action='store_true',
                        help='Use bulk write mode (覆盖现有数据, 节省 API 调用次数)')
    
    args = parser.parse_args()
    
    # 解析路径 - 支持多种调用方式
    json_path = Path(args.json_file)
    if not json_path.is_absolute():
        # 尝试多种路径组合
        script_dir = Path(__file__).parent
        possible_paths = [
            json_path,  # 当前工作目录下的相对路径
            script_dir / json_path,  # 脚本所在目录下的相对路径
            script_dir.parent / json_path,  # 项目根目录下的相对路径
        ]
        
        for p in possible_paths:
            if p.exists():
                json_path = p
                break
        else:
            # 如果都找不到，使用脚本所在目录下的路径（保持向后兼容）
            json_path = script_dir / json_path
    
    if not json_path.exists():
        print(f"Error: File not found: {json_path}")
        print(f"  Please ensure the path is correct relative to current directory or project root")
        sys.exit(1)
    
    # 确定失败记录文件和日志文件
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    if args.output_failed:
        failed_file = Path(args.output_failed)
    else:
        failed_file = Path(__file__).parent / f"failed_keys_{timestamp}.txt"
    
    log_file = Path(__file__).parent / f"import_log_{timestamp}.txt"
    retry_file = Path(args.retry_failed) if args.retry_failed else None
    
    # 设置日志
    logger = setup_logging(log_file)
    
    # 加载配置
    logger.info("Loading configuration...")
    config = load_config_from_env()
    namespace_id = load_kv_namespace()
    logger.info(f"Account ID: {config['account_id'][:8]}...")
    logger.info(f"Namespace:  {namespace_id[:8]}...")
    logger.info(f"Log file:   {log_file}")
    
    # 创建导入器并执行
    importer = KVImporter(
        account_id=config['account_id'],
        api_token=config['api_token'],
        namespace_id=namespace_id,
        logger=logger
    )
    
    success = importer.import_data(
        json_path=json_path,
        failed_keys_file=failed_file,
        retry_failed=retry_file,
        use_bulk=args.bulk
    )
    
    if success:
        logger.info("All entries imported successfully!")
        sys.exit(0)
    else:
        logger.error(f"{len(importer.failed_keys)} entries failed. Check {failed_file} for details.")
        sys.exit(1)


if __name__ == '__main__':
    main()
