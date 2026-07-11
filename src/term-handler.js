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
    // 列出所有 key（分页读取，CF KV list() 默认最多返回1000条）
    const allKeys = [];
    let cursor = undefined;
    do {
      const page = await env.TERM_GLOSSARY.list({ cursor, limit: 1000 });
      allKeys.push(...page.keys);
      cursor = page.cursor;
      console.log(`[TERM-READ] list() page fetched: ${page.keys.length} keys, total so far: ${allKeys.length}, hasMore: ${!!cursor}`);
    } while (cursor);
    console.log(`[TERM-READ] Found ${allKeys.length} keys in KV (all pages)`);

    // [DIAG] 检查 list() 结果中是否有 propodeum
    const keyNames = allKeys.map(k => k.name);
    const hasPropodeumKey = keyNames.some(n => n.toLowerCase() === "propodeum");
    console.log(`[DIAG] list() contains "propodeum": ${hasPropodeumKey}`);
    // 搜索类似 key
    const propodeumCandidates = keyNames.filter(n => n.toLowerCase().includes("propode"));
    if (propodeumCandidates.length > 0) {
      console.log(`[DIAG] Keys matching "propode*": ${JSON.stringify(propodeumCandidates.map(k => ({ name: k, charCodes: [...k].map(c => c.charCodeAt(0)) })))}`);
    } else {
      console.log(`[DIAG] No keys matching "propode*" found`);
    }
    
    if (allKeys.length === 0) {
      console.log("[TERM-READ] WARNING: No keys found in KV namespace");
      return [];
    }
    
    // 并行获取所有值
    const terms = await Promise.all(
      allKeys.map(async (keyObj) => {
        try {
          const value = await env.TERM_GLOSSARY.get(keyObj.name);
          if (keyObj.name.toLowerCase() === "propodeum") {
            console.log(`[DIAG] get("propodeum") returned: ${value === null ? "null" : value === undefined ? "undefined" : `string len=${value.length}`}`);
          }
          if (!value) {
            console.log(`[TERM-READ] WARNING: Key "${keyObj.name}" has no value`);
            return null;
          }
          
           // 解析 value JSON（新格式：data 为多源数组）
          const parsed = JSON.parse(value);
          const dataArray = Array.isArray(parsed.data) ? parsed.data : [];

          // [DIAG] 检查 propodeum 的解析情况
          if (keyObj.name === "propodeum") {
            console.log(`[DIAG] Key "propodeum" parsed OK. data type: ${typeof parsed.data}, isArray: ${Array.isArray(parsed.data)}, dataLen: ${dataArray.length}`);
            if (dataArray.length > 0) {
              dataArray.forEach((item, i) => {
                console.log(`[DIAG]   source[${i}]: ${item.metadata?.source}, detailed keys: ${Object.keys(item.detailed || {}).join(',')}`);
              });
            }
          }
          
          // 提取所有 source 的详细字段，用于术语高亮（只要有任一source包含此术语即可匹配）
          // 按优先级合并：取第一个有翻译的，或第一个有定义的，等等
          let merged = {
            translation: "",
            phonetic: "/null/",
            definition: "",
            id: "",
            synonyms: [],
            isA: [],
            sources: []
          };
          
          const FIELD_PRIORITY = {
            translation: ['my_term_202604', 'hao_core_2023', 'hao_inflect', 'engine_test'],
            phonetic: ['hao_core_2023', 'my_term_202604'],
            definition: ['hao_core_2023', 'my_term_202604']
          };
          
          // 按 source 排序：优先人工翻译
          const sortedData = [...dataArray].sort((a, b) => {
            const aSrc = a.metadata?.source || '';
            const bSrc = b.metadata?.source || '';
            const aIdx = FIELD_PRIORITY.translation.indexOf(aSrc);
            const bIdx = FIELD_PRIORITY.translation.indexOf(bSrc);
            return (aIdx === -1 ? 99 : aIdx) - (bIdx === -1 ? 99 : bIdx);
          });
          
          for (const item of sortedData) {
            const src = item.metadata?.source || 'unknown';
            const d = item.detailed || {};
            
            merged.sources.push(src);
            
            // translation: 取第一个有效的
            if (!merged.translation) {
              const t = d.translation || d.chinese_name || '';
              if (t && !t.startsWith('汉译')) {
                merged.translation = t;
              }
            }
            
            // phonetic: 从 HAO 优先
            if (!merged.phonetic || merged.phonetic === '/null/') {
              if (d.phonetic) merged.phonetic = d.phonetic;
            }
            
            // definition: 从 HAO 优先
            if (!merged.definition && d.def) {
              merged.definition = d.def;
            }
            
            // id: 取第一个有的（通常是HAO）
            if (!merged.id && d.id) {
              merged.id = d.id;
            }
            
            // synonyms: 合并
            if (d.synonyms && Array.isArray(d.synonyms)) {
              merged.synonyms.push(...d.synonyms.map(s => typeof s === 'string' ? s : s.name));
            }
            
            // is_a: 取第一个有的
            if (!merged.isA.length && d.is_a) {
              merged.isA = Array.isArray(d.is_a) ? d.is_a : [d.is_a];
            }
          }
          
          return {
            key: keyObj.name,
            id: merged.id,
            translation: merged.translation,
            phonetic: merged.phonetic,
            definition: merged.definition,
            synonyms: [...new Set(merged.synonyms)], // 去重
            isA: merged.isA,
            sources: merged.sources,
            rawData: dataArray // 保留原始数据供后续使用
          };
         } catch (err) {
          console.log(`[TERM-READ] ERROR parsing key "${keyObj.name}": ${err.message}`);
          // [DIAG] 详细记录解析失败的key
          if (keyObj.name === "propodeum") {
            console.log(`[DIAG] FAILED key "propodeum" value length: ${value?.length}, first 200 chars: ${value?.substring(0, 200)}`);
          }
          return null;
        }
      })
    );
    
    // 过滤掉无效的
    const validTerms = terms.filter(t => t !== null);
    console.log(`[TERM-READ] Successfully loaded ${validTerms.length} valid terms`);

    // [DIAG] 检查 propodeum 是否在有效列表中
    if (!validTerms.some(t => t.key === "propodeum")) {
      console.log(`[DIAG] ⚠️ Key "propodeum" NOT FOUND in validTerms!`);
    }
    
    // 打印前5个作为示例
    if (validTerms.length > 0) {
      const sample = validTerms.slice(0, 5);
      console.log(`[TERM-READ] Sample terms:`);
      sample.forEach(t => {
        const hasTranslation = t.translation && t.translation !== "";
        const synCount = t.synonyms ? t.synonyms.length : 0;
        console.log(`[TERM-READ]   - ${t.key} (ID:${t.id}, 翻译:${hasTranslation ? '✓' : '✗'}, 同义词:${synCount})`);
      });
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

  // [TEMP] 强制禁用缓存，用于诊断
  // if (termCache && now < termCacheExpiry) {
  //   console.log(`[TERM-READ] Using cached terms (${termCache.length} items)`);
  //   const diagKeys = ["propodeum", "mesoscutum", "nucha", "plica", "sulcus", "area", "corner", "depression", "callus"];
  //   diagKeys.forEach(k => {
  //     const found = termCache.some(t => t.key === k);
  //     if (!found) console.log(`[DIAG] ⚠️ [CACHE] Key "${k}" NOT in termCache!`);
  //   });
  //   return termCache;
  // }
  
  console.log("[TERM-READ] Cache disabled, reloading from KV...");
  termCache = await loadAllTerms(env);
  termCacheExpiry = now + CACHE_TTL_MS;

  // [DIAG] 检查 propodeum 是否在缓存中
  if (!termCache.some(t => t.key === "propodeum")) {
    console.log(`[DIAG] ⚠️ [FRESH LOAD] Key "propodeum" NOT in termCache after fresh load!`);
  } else {
    console.log(`[DIAG] ✓ [FRESH LOAD] Key "propodeum" found in termCache`);
  }
  
  return termCache;
}

// 构建正则表达式（匹配完整单词，保留大小写敏感）
export function buildTermRegex(terms) {
  if (!terms || terms.length === 0) {
    console.log("[TERM-READ] No terms available for regex building");
    return null;
  }
  
  // 过滤长度小于 3 的术语（避免匹配 "1", "A", "1A" 等编号）
  const validTerms = terms.filter(t => t.key && t.key.length >= 3);
  console.log(`[TERM-READ] Filtered ${terms.length - validTerms.length} short terms (<3 chars), ${validTerms.length} remaining`);

  // [DIAG] 检查 propodeum 是否通过长度过滤
  if (!validTerms.some(t => t.key === "propodeum")) {
    console.log(`[DIAG] ⚠️ Key "propodeum" NOT in validTerms after length filter!`);
  }
  
  // 转义特殊字符并按长度降序排序（优先匹配长术语）
  const escaped = validTerms
    .map(t => t.key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .sort((a, b) => b.length - a.length);
  
  // 使用单词边界，但考虑连字符和斜杠
  // \b 在单词字符(\w)和非单词字符间匹配
  // 这里我们用 lookahead/lookbehind 来处理更复杂的情况
  const pattern = escaped.join('|');
  
  try {
    // 大小写敏感，全局匹配
    const regex = new RegExp(`\\b(${pattern})\\b`, 'g');
    console.log(`[TERM-READ] Built regex with ${escaped.length} patterns, pattern length: ${pattern.length}`);

    // [DIAG] 检查 propodeum 在正则中的状态
    console.log(`[DIAG] "propodeum" in escaped: ${escaped.includes("propodeum")}`);

    // [DIAG] 用正则直接测试特定文本
    const testText = "Median area of propodeum: evenly reticulate";
    regex.lastIndex = 0;
    const testResult = regex.test(testText);
    console.log(`[DIAG] Regex test on "${testText}": ${testResult}, lastIndex after: ${regex.lastIndex}`);

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
