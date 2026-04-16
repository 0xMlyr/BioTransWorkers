// 术语处理器 - 从 KV 加载全部术语并缓存

let termCache = null;
let termCacheExpiry = 0;
const CACHE_TTL_MS = 5 * 60 * 1000; // 5分钟缓存

// 从 KV 加载全部术语
async function loadAllTerms(env) {
  console.log("[TERM-READ] Starting to load all terms from KV...");
  
  if (!env.TERM_GLOSSARY) {
    console.log("[TERM-READ] ERROR: TERM_GLOSSARY binding not found!");
    return [];
  }
  
  try {
    // 列出所有 key
    const keys = await env.TERM_GLOSSARY.list();
    console.log(`[TERM-READ] Found ${keys.keys.length} keys in KV`);
    
    if (keys.keys.length === 0) {
      console.log("[TERM-READ] WARNING: No keys found in KV namespace");
      return [];
    }
    
    // 并行获取所有值
    const terms = await Promise.all(
      keys.keys.map(async (keyObj) => {
        try {
          const value = await env.TERM_GLOSSARY.get(keyObj.name);
          if (!value) {
            console.log(`[TERM-READ] WARNING: Key "${keyObj.name}" has no value`);
            return null;
          }
          
          // 解析 value JSON
          const parsed = JSON.parse(value);
          return {
            key: keyObj.name,
            translation: parsed.translation || "",
            phonetic: parsed.phonetic || ""
          };
        } catch (err) {
          console.log(`[TERM-READ] ERROR parsing key "${keyObj.name}": ${err.message}`);
          return null;
        }
      })
    );
    
    // 过滤掉无效的
    const validTerms = terms.filter(t => t !== null);
    console.log(`[TERM-READ] Successfully loaded ${validTerms.length} valid terms`);
    
    // 打印前5个作为示例
    if (validTerms.length > 0) {
      const sample = validTerms.slice(0, 5).map(t => t.key).join(", ");
      console.log(`[TERM-READ] Sample terms: ${sample}...`);
    }
    
    return validTerms;
  } catch (err) {
    console.log(`[TERM-READ] ERROR loading terms: ${err.message}`);
    return [];
  }
}

// 获取术语列表（带缓存）
export async function getTerms(env) {
  const now = Date.now();
  
  if (termCache && now < termCacheExpiry) {
    console.log(`[TERM-READ] Using cached terms (${termCache.length} items)`);
    return termCache;
  }
  
  console.log("[TERM-READ] Cache expired or empty, reloading...");
  termCache = await loadAllTerms(env);
  termCacheExpiry = now + CACHE_TTL_MS;
  
  return termCache;
}

// 构建正则表达式（匹配完整单词，保留大小写敏感）
export function buildTermRegex(terms) {
  if (!terms || terms.length === 0) {
    console.log("[TERM-READ] No terms available for regex building");
    return null;
  }
  
  // 转义特殊字符并按长度降序排序（优先匹配长术语）
  const escaped = terms
    .map(t => t.key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .sort((a, b) => b.length - a.length);
  
  // 使用单词边界，但考虑连字符和斜杠
  // \b 在单词字符(\w)和非单词字符间匹配
  // 这里我们用 lookahead/lookbehind 来处理更复杂的情况
  const pattern = escaped.join('|');
  
  try {
    // 大小写敏感，全局匹配
    const regex = new RegExp(`\\b(${pattern})\\b`, 'g');
    console.log(`[TERM-READ] Built regex with ${escaped.length} patterns`);
    return regex;
  } catch (err) {
    console.log(`[TERM-READ] ERROR building regex: ${err.message}`);
    return null;
  }
}

// 创建文本处理器
export function createTextHandler(terms, regex) {
  if (!regex || !terms || terms.length === 0) {
    console.log("[TERM-READ] No regex/terms available, text handler will pass through");
    return {
      text(text) {
        // 不做任何处理
      }
    };
  }
  
  // 创建术语到翻译的映射
  const termMap = new Map(terms.map(t => [t.key, t.translation]));
  
  return {
    text(text) {
      const content = text.text;
      if (!content || typeof content !== 'string') return;
      
      // 检查是否包含英文术语（简单启发式：检查是否有匹配）
      regex.lastIndex = 0;
      if (!regex.test(content)) {
        // 没有匹配，保持原样
        return;
      }
      
      // 重置 lastIndex
      regex.lastIndex = 0;
      
      // 替换所有匹配
      let lastIndex = 0;
      let match;
      let hasReplacement = false;
      
      while ((match = regex.exec(content)) !== null) {
        const term = match[0];
        const matchStart = match.index;
        const matchEnd = matchStart + term.length;
        
        // 输出匹配到的术语（用于调试）
        if (!hasReplacement) {
          console.log(`[TERM-READ] First match in text: "${term}"`);
        }
        hasReplacement = true;
        
        // 保留匹配前的文本
        if (matchStart > lastIndex) {
          // 保留原始文本片段
        }
        
        // 替换为带 span 的版本
        const translation = termMap.get(term) || "";
        const replacement = `<span class="bio-term" data-term="${term}" title="${translation}">${term}</span>`;
        
        lastIndex = matchEnd;
      }
      
      if (hasReplacement) {
        // 执行实际替换
        const replaced = content.replace(regex, (match) => {
          const translation = termMap.get(match) || "";
          return `<span class="bio-term" data-term="${match}" title="${translation}">${match}</span>`;
        });
        
        text.replace(replaced, { html: true });
        console.log(`[TERM-READ] Replaced terms in text segment`);
      }
    }
  };
}
