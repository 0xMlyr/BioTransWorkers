// AC自动机术语处理器
// 职责：加载Trie、AC匹配算法

let trieCache = null;
let trieCacheExpiry = 0;
const CACHE_TTL_MS = 5 * 60 * 1000;

// 从 KV 加载 AC 自动机 Trie
export async function loadTrie(env) {
  const now = Date.now();
  if (trieCache && now < trieCacheExpiry) {
    console.log(`[AC] Using cached trie`);
    return trieCache;
  }

  console.log("[AC] Loading trie from KV...");
  if (!env.TERM_ACTRIE) {
    console.log("[AC] ERROR: TERM_ACTRIE binding not found!");
    return null;
  }

  const raw = await env.TERM_ACTRIE.get("ac_trie");
  if (!raw) {
    console.log("[AC] ERROR: ac_trie key not found in KV");
    return null;
  }

  try {
    const data = JSON.parse(raw);
    trieCache = data.trie;
    trieCacheExpiry = now + CACHE_TTL_MS;
    console.log(`[AC] Loaded trie: ${data.term_count} terms, ${data.node_count} nodes`);
    return trieCache;
  } catch (err) {
    console.log(`[AC] ERROR parsing trie: ${err.message}`);
    return null;
  }
}

// AC 自动机匹配
// 返回 [{ term, start, end }, ...] 已过滤单词边界、已去重、非重叠
export function acMatch(text, trie) {
  if (!trie || !text || text.length === 0) return [];

  const lower = text.toLowerCase();
  const rawMatches = [];
  let state = 0;

  for (let i = 0; i < lower.length; i++) {
    const ch = lower[i];
    while (state !== 0 && !trie[state].children[ch]) {
      state = trie[state].fail;
    }
    state = trie[state].children[ch] || 0;

    for (const term of trie[state].output) {
      rawMatches.push({ term, start: i - term.length + 1, end: i + 1 });
    }
  }

  // 单词边界过滤
  const withBoundaries = rawMatches.filter(m => {
    if (m.start > 0 && /\w/.test(text[m.start - 1])) return false;
    if (m.end < text.length && /\w/.test(text[m.end])) return false;
    return true;
  });

  // 排序：按起始位置优先、同位置长词优先
  withBoundaries.sort((a, b) => a.start - b.start || (b.end - b.start) - (a.end - a.start));

  // 贪心去重叠：同位置取最长，不同位置取先出现的
  const final = [];
  let lastEnd = 0;
  for (const m of withBoundaries) {
    if (m.start >= lastEnd) {
      final.push(m);
      lastEnd = m.end;
    }
  }

  return final;
}
