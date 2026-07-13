import { pensoftConfig } from "./pensoft.js";

const ALLOWED_DOMAINS = [
  "mdpi.com",
  "plos.org",
  "zookeys.pensoft.net",
  "zootaxa.pensoft.net",
  "ncbi.nlm.nih.gov",
  "europeanjournaloftaxonomy.eu",
  "mapress.com",
];

export function isAllowedDomain(hostname) {
  hostname = hostname.toLowerCase();
  for (const domain of ALLOWED_DOMAINS) {
    if (hostname === domain || hostname.endsWith("." + domain)) return true;
  }
  return false;
}

// key 为域名后缀，支持子域名匹配
const SITE_MAP = new Map([
  ["pensoft.net", pensoftConfig],
]);

export function getSiteConfig(hostname) {
  for (const [key, config] of SITE_MAP) {
    if (hostname === key || hostname.endsWith("." + key)) return config;
  }
  return {};
}
