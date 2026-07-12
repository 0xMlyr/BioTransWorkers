#!/usr/bin/env python3
"""
KV 安全并入脚本 (并发版)
Phase 1: 全量读取(并发) → 本地合并 → 审计
Phase 2: --upload 批量写入

用法:
    python merge_to_kv.py                    # Phase 1
    python merge_to_kv.py --upload <file>    # Phase 2

突破点: 使用 ThreadPoolExecutor 并发读取, 2-3x 速度提升
REST API: 1200次/5min(token), 200次/s(IP), 本脚本用3并发 ≈ 4req/s 在限额内
"""

import json
import re
import sys
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Dict, List
import requests

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent
HAO_EXPAND_JSON = SCRIPT_DIR / "hao_expand_for_kv.json"

# 并发控制
MAX_WORKERS = 3
REQUEST_DELAY = 0.25  # 每个请求间最小间隔(秒), 确保 ≤4req/s


class RateLimiter:
    """线程安全的请求频率控制"""
    def __init__(self, min_interval: float = 0.25):
        self._min_interval = min_interval
        self._last_request = 0.0
        self._lock = Lock()
        self._count_5min = 0
        self._window_start = time.time()

    def wait(self):
        with self._lock:
            now = time.time()
            # 检查 5 分钟窗口
            if now - self._window_start >= 300:
                self._window_start = now
                self._count_5min = 0
            # 如果接近限额, 等待
            if self._count_5min >= 1150:
                wait_time = self._window_start + 300 - now + 1
                if wait_time > 0:
                    time.sleep(wait_time)
                    self._window_start = time.time()
                    self._count_5min = 0
                    now = self._window_start
            # 最小间隔
            elapsed = now - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.time()
            self._count_5min += 1


def setup_logging(log_file: Path) -> logging.Logger:
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers = []
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger


def load_config() -> tuple[str, str, str]:
    dev_vars = PROJECT_ROOT / ".dev.vars"
    if not dev_vars.exists():
        raise FileNotFoundError(f"Config not found: {dev_vars}")
    config: dict[str, str] = {}
    with open(dev_vars, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
    account_id = config.get("CF_ACCOUNT_ID", "")
    api_token = config.get("CF_API_TOKEN", "")
    wrangler_path = PROJECT_ROOT / "wrangler.jsonc"
    content = wrangler_path.read_text(encoding="utf-8")
    match = re.search(r'"binding"\s*:\s*"TERM_GLOSSARY".*?"id"\s*:\s*"([a-f0-9]+)"', content, re.DOTALL)
    if not match:
        raise ValueError("Could not find TERM_GLOSSARY namespace id")
    return account_id, api_token, match.group(1)


def list_all_keys(base_url: str, headers: dict, logger: logging.Logger) -> List[str]:
    all_keys: List[str] = []
    cursor: str | None = None
    page = 0
    while True:
        page += 1
        url = f"{base_url}/keys?limit=1000"
        if cursor:
            url += f"&cursor={cursor}"
        logger.info(f"List keys page {page}...")
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"List failed: {data.get('errors')}")
        for item in data.get("result", []):
            all_keys.append(item["name"])
        logger.info(f"  Page {page}: {len(data['result'])} keys (total: {len(all_keys)})")
        cursor = data.get("result_info", {}).get("cursor")
        if not cursor:
            break
    logger.info(f"Total keys: {len(all_keys)}")
    return all_keys


def download_all_concurrent(
    keys: List[str],
    base_url: str,
    headers: dict,
    logger: logging.Logger,
    rate_limiter: RateLimiter,
) -> Dict[str, dict]:
    values: Dict[str, dict] = {}
    failed_keys: List[str] = []
    total = len(keys)
    completed = 0
    lock = Lock()

    def fetch_one(key: str) -> tuple[str, dict | None]:
        rate_limiter.wait()
        try:
            resp = requests.get(f"{base_url}/values/{key}", headers=headers, timeout=30)
            if resp.status_code == 200:
                return key, json.loads(resp.text)
            elif resp.status_code == 404:
                return key, None
            else:
                logger.debug(f"HTTP {resp.status_code} for '{key}'")
                return key, None
        except Exception as e:
            logger.debug(f"Error '{key}': {e}")
            return key, None

    logger.info(f"Downloading {total} keys with {MAX_WORKERS} workers...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_one, k): k for k in keys}
        for future in as_completed(futures):
            key, val = future.result()
            with lock:
                completed += 1
                if val is not None:
                    values[key] = val
                else:
                    failed_keys.append(key)
                if completed % 50 == 0 or completed == total:
                    logger.info(f"Download [{completed}/{total}] ({(completed/total)*100:.1f}%)")

    logger.info(f"Done: {len(values)} values, {len(failed_keys)} failures")
    if failed_keys:
        logger.warning(f"Failed keys: {failed_keys}")
    return values, failed_keys


def merge_local(existing: Dict[str, dict], new_entries: List[dict], logger: logging.Logger) -> tuple[Dict[str, dict], dict]:
    merged = dict(existing)
    stats = {"new": 0, "merged": 0, "unchanged": 0, "total_new": len(new_entries)}
    new_source = new_entries[0]["value"]["data"][0]["metadata"]["source"] if new_entries else "?"

    for entry in new_entries:
        key = entry["key"]
        new_value = entry["value"]
        new_data = new_value["data"] if isinstance(new_value, dict) else new_value
        if not isinstance(new_data, list):
            new_data = [new_data]

        if key not in merged:
            merged[key] = {"data": new_data}
            stats["new"] += 1
        else:
            existing_data = merged[key].get("data", [])
            if not isinstance(existing_data, list):
                existing_data = [existing_data]
            existing_sources = {item.get("metadata", {}).get("source") for item in existing_data}
            if new_source in existing_sources:
                stats["unchanged"] += 1
            else:
                existing_data.extend(new_data)
                merged[key] = {"data": existing_data}
                stats["merged"] += 1

    logger.info(f"Merge: {stats['new']} new, {stats['merged']} merged, {stats['unchanged']} skipped")
    return merged, stats


def save_json(data, path: Path, logger: logging.Logger):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved: {path} ({path.stat().st_size:,} bytes)")


def load_json(path: Path, logger: logging.Logger) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def upload_bulk(base_url: str, headers: dict, merged: Dict[str, dict], logger: logging.Logger):
    entries = [{"key": k, "value": json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v}
               for k, v in merged.items()]
    total = len(entries)
    batch_size = 5000

    logger.info(f"Bulk upload: {total} entries")
    logger.info("WARNING: This will overwrite all data in the namespace!")

    for i in range(0, total, batch_size):
        batch = entries[i:i + batch_size]
        bn = i // batch_size + 1
        tb = (total + batch_size - 1) // batch_size
        logger.info(f"Batch {bn}/{tb}: {len(batch)} entries...")
        resp = requests.put(f"{base_url}/bulk", headers=headers, json=batch, timeout=120)
        data = resp.json()
        if data.get("success"):
            logger.info(f"  Batch {bn} OK")
        else:
            logger.error(f"  Batch {bn} FAILED: {data.get('errors')}")
    logger.info("Upload complete.")


def main():
    parser = argparse.ArgumentParser(description="KV安全并入脚本 (并发版)")
    parser.add_argument("--upload", help="上传合并后的 JSON 到 KV (Phase 2)")
    parser.add_argument("--yes", action="store_true", help="跳过上传确认提示")
    parser.add_argument("--from-backup", help="使用已有备份跳过下载")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = SCRIPT_DIR / f"merge_log_{timestamp}.txt"
    logger = setup_logging(log_file)
    logger.info(f"Log: {log_file}")

    account_id, api_token, namespace_id = load_config()
    base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/storage/kv/namespaces/{namespace_id}"
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    logger.info(f"Namespace: {namespace_id[:8]}...")

    # ── Phase 2: Upload ──
    if args.upload:
        upload_path = Path(args.upload)
        if not upload_path.exists():
            logger.error(f"Not found: {upload_path}")
            sys.exit(1)
        merged = load_json(upload_path, logger)
        logger.info(f"Loaded {len(merged)} entries")
        if not args.yes:
            ans = input(f"\nUpload {len(merged)} entries to KV? Type YES: ").strip()
            if ans != "YES":
                logger.info("Cancelled.")
                sys.exit(0)
        upload_bulk(base_url, headers, merged, logger)
        return

    # ── Phase 1: Download + Merge ──
    if not HAO_EXPAND_JSON.exists():
        logger.error(f"Not found: {HAO_EXPAND_JSON}. Run build_kv.py first.")
        sys.exit(1)
    new_entries = load_json(HAO_EXPAND_JSON, logger)
    logger.info(f"New entries: {len(new_entries)}")

    if args.from_backup:
        backup_path = Path(args.from_backup)
        existing = load_json(backup_path, logger)
        logger.info(f"Loaded {len(existing)} from backup")
    else:
        logger.info("── List keys ──")
        keys = list_all_keys(base_url, headers, logger)
        backup_path = SCRIPT_DIR / f"kv_backup_{timestamp}.json"

        logger.info(f"── Download {len(keys)} values (concurrent) ──")
        rate_limiter = RateLimiter(REQUEST_DELAY)
        existing, failed_keys = download_all_concurrent(keys, base_url, headers, logger, rate_limiter)

        # 重试失败 key
        if failed_keys:
            logger.info(f"Retrying {len(failed_keys)} failed keys...")
            for key in failed_keys:
                rate_limiter.wait()
                try:
                    resp = requests.get(f"{base_url}/values/{key}", headers=headers, timeout=30)
                    if resp.status_code == 200:
                        existing[key] = json.loads(resp.text)
                        logger.info(f"  Retry OK: '{key}'")
                        failed_keys.remove(key)
                    else:
                        logger.warning(f"  Retry FAIL: '{key}' HTTP {resp.status_code}")
                except Exception as e:
                    logger.warning(f"  Retry ERROR: '{key}' {e}")
            if failed_keys:
                logger.error(f"Still failed after retry: {failed_keys}")
                logger.error("Aborting to prevent data loss. Run again after fixing network.")
                sys.exit(1)

        save_json(existing, backup_path, logger)

    logger.info("── Merge ──")
    merged, stats = merge_local(existing, new_entries, logger)

    logger.info("=" * 50)
    logger.info(f"Existing: {len(existing)}  |  New entries: {stats['total_new']}")
    logger.info(f"  + New keys:    {stats['new']}")
    logger.info(f"  + Merged:      {stats['merged']}")
    logger.info(f"  - Skipped:     {stats['unchanged']}")
    logger.info(f"  = Total:       {len(merged)}")
    logger.info("=" * 50)

    merged_path = SCRIPT_DIR / f"kv_merged_{timestamp}.json"
    save_json(merged, merged_path, logger)

    # 抽样验证: 检查 "abdomen" 的多数据源
    sample_key = "abdomen"
    if sample_key in merged:
        sources = [d["metadata"]["source"] for d in merged[sample_key].get("data", [])]
        logger.info(f"Sample '{sample_key}': sources = {sources}")

    logger.info("")
    logger.info("Phase 1 done. Review the merged file:")
    logger.info(f"  Backup: {backup_path}")
    logger.info(f"  Merged: {merged_path}")
    logger.info(f"Run: python merge_to_kv.py --upload {merged_path.name}")


if __name__ == "__main__":
    main()
