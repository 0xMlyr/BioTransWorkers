import { pensoftConfig } from "./pensoft.js";

// key 为域名后缀，支持子域名匹配（同 ALLOWED_HOSTS 逻辑）
const SITE_MAP = new Map([
  ["pensoft.net", pensoftConfig],
]);

export function getSiteConfig(hostname) {
  for (const [key, config] of SITE_MAP) {
    if (hostname === key || hostname.endsWith("." + key)) return config;
  }
  return {};
}
