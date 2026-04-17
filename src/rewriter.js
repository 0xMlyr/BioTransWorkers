function decodeHtmlEntities(str) {
  return str.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
}

function toProxyUrl(original, base, workerOrigin) {
  if (!original) return original;
  if (original.startsWith("data:") || original.startsWith("blob:") || original.startsWith("javascript:")) return original;
  try {
    const absolute = new URL(decodeHtmlEntities(original), base).href;
    return `${workerOrigin}/?url=${encodeURIComponent(absolute)}`;
  } catch {
    return original;
  }
}

class AttributeRewriter {
  constructor(attr, base, workerOrigin) {
    this.attr = attr;
    this.base = base;
    this.workerOrigin = workerOrigin;
  }
  element(el) {
    const val = el.getAttribute(this.attr);
    if (val) el.setAttribute(this.attr, toProxyUrl(val, this.base, this.workerOrigin));
  }
}

// 专门的 href 处理器：跳过锚点链接和 javascript: 协议
class HrefRewriter {
  constructor(base, workerOrigin) {
    this.base = base;
    this.workerOrigin = workerOrigin;
  }
  element(el) {
    const val = el.getAttribute("href");
    if (!val) return;
    // 锚点链接和 javascript: 协议不需要代理
    if (val.startsWith("#") || val.startsWith("javascript:")) {
      console.log(`[REWRITE] Skipping anchor/js href: ${val.substring(0, 50)}`);
      return;
    }
    const newVal = toProxyUrl(val, this.base, this.workerOrigin);
    if (newVal !== val) {
      console.log(`[REWRITE] href: ${val.substring(0, 60)}... -> ${newVal.substring(0, 60)}...`);
    }
    el.setAttribute("href", newVal);
  }
}

class BaseRemover {
  element(el) { el.remove(); }
}

class ScriptRewriter {
  constructor(attr, base, workerOrigin, blocklist) {
    this.attr = attr;
    this.base = base;
    this.workerOrigin = workerOrigin;
    this.blocklist = blocklist;
  }
  element(el) {
    const val = el.getAttribute(this.attr);
    if (!val) return;
    if (this.blocklist.some(re => re.test(val))) {
      console.log(`[BLOCK] Script removed: ${val.substring(0, 80)}...`);
      el.remove();
      return;
    }
    const newVal = toProxyUrl(val, this.base, this.workerOrigin);
    if (newVal !== val) {
      console.log(`[REWRITE] script src: ${val.substring(0, 50)}... -> ${newVal.substring(0, 50)}...`);
    }
    el.setAttribute(this.attr, newVal);
  }
}

class SrcsetRewriter {
  constructor(attr, base, workerOrigin) {
    this.attr = attr;
    this.base = base;
    this.workerOrigin = workerOrigin;
  }
  element(el) {
    const val = el.getAttribute(this.attr);
    if (!val) return;
    const rewritten = val.split(",").map(part => {
      const [url, ...descriptor] = part.trim().split(/\s+/);
      const proxied = toProxyUrl(url, this.base, this.workerOrigin);
      return descriptor.length ? `${proxied} ${descriptor.join(" ")}` : proxied;
    }).join(", ");
    el.setAttribute(this.attr, rewritten);
  }
}

// 通用脚本黑名单：这些外部脚本会在运行时动态加载子资源，代理后无法正常工作
const GLOBAL_SCRIPT_BLOCKLIST = [
  /maps\.googleapis\.com/i,
  /maps\.gstatic\.com/i,
];

export function applyRewriter(rewriter, finalUrl, workerOrigin, siteConfig = {}, terms = [], termRegex = null) {
  const base = finalUrl;
  const scriptBlocklist = [...GLOBAL_SCRIPT_BLOCKLIST, ...(siteConfig.scriptBlocklist ?? [])];
  console.log(`[REWRITER] Base: ${base}, Blocklist count: ${scriptBlocklist.length}`);

  // 创建术语处理器
  const termHandler = createTermHandler(terms, termRegex);

  rewriter.on("head", {
    element(el) {
      console.log("[REWRITER] <head> found - injecting SW registration and term styles");
      // 注入 Service Worker 注册
      el.prepend(`<script>(function(){if(!navigator.serviceWorker)return;navigator.serviceWorker.register('/sw.js',{scope:'/'}).catch(function(){});})();</script>`, { html: true });
      
      // 注入术语高亮样式（弹窗样式移到 body 注入以确保优先级）
      const termStyles = `<style>
.bio-term {
  background: linear-gradient(180deg, rgba(46,125,50,0.15) 0%, rgba(46,125,50,0.25) 100%);
  border-bottom: 1px dotted #2e7d32;
  padding: 0 2px;
  border-radius: 2px;
  cursor: pointer;
  transition: background 0.2s ease;
}
.bio-term:hover {
  background: linear-gradient(180deg, rgba(46,125,50,0.25) 0%, rgba(46,125,50,0.35) 100%);
  border-bottom: 1px solid #2e7d32;
}
</style>`;
      el.append(termStyles, { html: true });
      console.log("[TERM-READ] Injected term highlight styles");
    }
  });

  rewriter.on("base", {
    element(el) {
      console.log("[REWRITER] <base> found - removing");
      el.remove();
    }
  });

  // 在 body 注入 - 区分主页面和 iframe
  rewriter.on("body", {
    element(el) {
      // 检测是否在 iframe 中的脚本
      const iframeDetectionScript = `<script>
(function() {
  const isInIframe = window.self !== window.top;
  console.log('[BioTrans] Page context:', isInIframe ? 'iframe' : 'main page');
  
  if (!isInIframe) {
    // ===== 主页面：注入弹窗 =====
    console.log('[BioTrans] Injecting popup in main page');
    
    // 弹窗样式 - 匹配 webpage.js 深色主题
    const popupStyles = document.createElement('style');
    popupStyles.textContent = \`
#bio-term-popup {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  width: 400px;
  max-width: 90vw;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 4px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  z-index: 2147483647;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  display: none;
  color: #e0e0e0;
}
#bio-term-popup.active { display: block !important; }
#bio-term-popup .popup-header { 
  padding: 14px 16px 10px; 
  border-bottom: 1px solid #2a2a2a; 
  position: relative;
  background: #1a1a1a;
}
#bio-term-popup .popup-term { 
  font-size: 15px; 
  font-weight: 500; 
  color: #4caf50; 
  margin: 0 0 6px 0; 
  word-break: break-word; 
  padding-right: 36px;
  letter-spacing: 0.02em;
}
#bio-term-popup .popup-phonetic { 
  font-size: 12px; 
  color: #888; 
  font-style: normal; 
  margin: 0;
  opacity: 0.8;
}
#bio-term-popup .popup-def {
  font-size: 11px;
  color: #666;
  line-height: 1.5;
  margin: 8px 0 0 0;
  max-height: 80px;
  overflow-y: auto;
}
#bio-term-popup .popup-def:empty {
  display: none;
}
#bio-term-popup .popup-body { 
  padding: 12px 16px 14px; 
  background: #1a1a1a;
}
#bio-term-popup .popup-translation { 
  font-size: 14px; 
  color: #e0e0e0; 
  margin: 0; 
  font-weight: 400;
  line-height: 1.7;
}
#bio-term-popup .popup-translation:empty::before {
  content: "暂无翻译";
  color: #666;
  font-style: italic;
}
#bio-term-popup .popup-countdown { 
  position: absolute; 
  top: 10px; 
  right: 12px; 
  width: 24px; 
  height: 24px; 
  border-radius: 3px; 
  background: #2a2a2a; 
  border: 1px solid #4caf50;
  color: #4caf50; 
  font-size: 11px; 
  font-weight: 500; 
  display: flex; 
  align-items: center; 
  justify-content: center;
  font-family: inherit;
}
\`;
    document.head.appendChild(popupStyles);
    
    // 弹窗 HTML
    const popupDiv = document.createElement('div');
    popupDiv.id = 'bio-term-popup';
    popupDiv.innerHTML = \`
      <div class="popup-header">
        <div class="popup-countdown">5</div>
        <p class="popup-term"></p>
        <p class="popup-phonetic"></p>
        <p class="popup-def"></p>
      </div>
      <div class="popup-body">
        <p class="popup-translation"></p>
      </div>
    \`;
    document.body.appendChild(popupDiv);
    
    // 弹窗控制逻辑
    const popup = document.getElementById('bio-term-popup');
    const popupTerm = popup.querySelector('.popup-term');
    const popupPhonetic = popup.querySelector('.popup-phonetic');
    const popupDef = popup.querySelector('.popup-def');
    const popupTranslation = popup.querySelector('.popup-translation');
    const popupCountdown = popup.querySelector('.popup-countdown');
    let countdownTimer = null;
    let countdownValue = 5;
    
    function closePopup() {
      popup.classList.remove('active');
      if (countdownTimer) {
        clearInterval(countdownTimer);
        countdownTimer = null;
      }
    }
    
    function showPopup(term) {
      console.log('[BioTrans] Main page showing popup:', term);
      
      // 清除之前的倒计时
      if (countdownTimer) {
        clearInterval(countdownTimer);
      }
      
      popupTerm.textContent = term.name || term.key;
      popupPhonetic.textContent = term.phonetic || '/null/';
      popupDef.textContent = term.def || '';
      popupTranslation.textContent = term.translation || '';
      
      // 重置并显示倒计时
      countdownValue = 5;
      popupCountdown.textContent = countdownValue;
      popup.classList.add('active');
      
      // 启动倒计时
      countdownTimer = setInterval(function() {
        countdownValue--;
        popupCountdown.textContent = countdownValue;
        if (countdownValue <= 0) {
          clearInterval(countdownTimer);
          countdownTimer = null;
          closePopup();
          console.log('[BioTrans] Auto-closed popup after 5s');
        }
      }, 1000);
      
      console.log('[BioTrans] Popup displayed with 5s countdown');
    }
    
    // 接收来自 iframe 的术语点击消息
    window.addEventListener('message', function(e) {
      if (e.data && e.data.type === 'BIOTERM_SHOW') {
        console.log('[BioTrans] Received term from iframe:', e.data.term);
        showPopup(e.data.term);
      }
    });
    
    console.log('[BioTrans] Main page popup ready');
    
    // ===== 首屏欢迎弹窗 =====
    const welcomeStyles = document.createElement('style');
    welcomeStyles.textContent = \`
#bio-welcome-popup {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  width: 440px;
  max-width: 90vw;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 4px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  z-index: 2147483646;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.7;
  display: none;
  color: #e0e0e0;
}
#bio-welcome-popup.active { display: block !important; }
#bio-welcome-popup .welcome-header {
  padding: 14px 16px 10px;
  border-bottom: 1px solid #2a2a2a;
  position: relative;
  background: #1a1a1a;
}
#bio-welcome-popup .welcome-title {
  font-size: 14px;
  font-weight: 500;
  color: #4caf50;
  margin: 0;
  letter-spacing: 0.02em;
  padding-right: 36px;
}
#bio-welcome-popup .welcome-body {
  padding: 12px 16px 14px;
  background: #1a1a1a;
}
#bio-welcome-popup .welcome-line {
  margin: 6px 0;
  color: #e0e0e0;
  text-align: left;
}
#bio-welcome-popup .welcome-line.highlight {
  color: #888;
  font-size: 12px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #2a2a2a;
}
#bio-welcome-popup .welcome-line.powered {
  color: #4caf50;
  font-size: 11px;
  margin-top: 8px;
  opacity: 0.9;
}
#bio-welcome-popup .welcome-close {
  position: absolute;
  top: 10px;
  right: 12px;
  width: 24px;
  height: 24px;
  border-radius: 3px;
  background: #2a2a2a;
  border: 1px solid #4caf50;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s ease;
}
#bio-welcome-popup .welcome-close:hover {
  background: #333;
}
#bio-welcome-popup .welcome-close::before,
#bio-welcome-popup .welcome-close::after {
  content: '';
  position: absolute;
  width: 14px;
  height: 2px;
  background: #4caf50;
  border-radius: 1px;
}
#bio-welcome-popup .welcome-close::before {
  transform: rotate(45deg);
}
#bio-welcome-popup .welcome-close::after {
  transform: rotate(-45deg);
}
\`;
    document.head.appendChild(welcomeStyles);
    
    const welcomeDiv = document.createElement('div');
    welcomeDiv.id = 'bio-welcome-popup';
    welcomeDiv.innerHTML = \`
      <div class="welcome-header">
        <button class="welcome-close" aria-label="关闭"></button>
        <p class="welcome-title">BioTrans 术语翻译代理</p>
      </div>
      <div class="welcome-body">
        <p class="welcome-line">当前页面已被 <span style="color:#4caf50">biotrans.mlyr.top</span> 代理</p>
        <p class="welcome-line">可点击高亮词汇查看翻译</p>
        <p class="welcome-line highlight">本代理站不存储任何数据，版权归原作者及出版商所有</p>
        <p class="welcome-line powered">Powered by MLYR Bio-Trans</p>
      </div>
    \`;
    document.body.appendChild(welcomeDiv);
    
    // 欢迎弹窗控制
    const welcomePopup = document.getElementById('bio-welcome-popup');
    
    function closeWelcome() {
      welcomePopup.classList.remove('active');
      console.log('[BioTrans] Welcome popup closed by user');
    }
    
    function showWelcome() {
      welcomePopup.classList.add('active');
      console.log('[BioTrans] Welcome popup displayed, waiting for user to close');
    }
    
    // 绑定关闭按钮事件
    welcomePopup.querySelector('.welcome-close').addEventListener('click', closeWelcome);
    
    // 页面加载后自动显示欢迎弹窗
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', showWelcome);
    } else {
      showWelcome();
    }
    
  } else {
    // ===== iframe：发送点击事件到主页面 =====
    console.log('[BioTrans] Setting up iframe term click handler');
    
    document.addEventListener('click', function(e) {
      const termEl = e.target.closest('.bio-term');
      if (!termEl) return;
      
      e.preventDefault();
      e.stopPropagation();
      
      const termKey = termEl.getAttribute('data-term');
      if (!termKey) return;
      
      console.log('[BioTrans] iframe term clicked:', termKey);
      
      // 获取术语数据并发送到主页面
      fetch('/api/term?key=' + encodeURIComponent(termKey))
        .then(function(res) { return res.json(); })
        .then(function(data) {
          console.log('[BioTrans] iframe sending term data to parent:', data);
          window.parent.postMessage({ type: 'BIOTERM_SHOW', term: data }, '*');
        })
        .catch(function(err) {
          console.error('[BioTrans] Failed to fetch term:', err);
          window.parent.postMessage({ 
            type: 'BIOTERM_SHOW', 
            term: { key: termKey, name: termKey, translation: '', phonetic: '/null/' }
          }, '*');
        });
    });
    
    console.log('[BioTrans] iframe click handler ready');
  }
})();
</script>`;
      
      el.append(iframeDetectionScript, { html: true });
      console.log("[REWRITER] Injected cross-frame popup system");
    }
  });

  rewriter.on("a[href]",                    new HrefRewriter(base, workerOrigin));
  rewriter.on("div[href]",                  new HrefRewriter(base, workerOrigin)); // MDPI 特殊用法
  rewriter.on("*[data-counterslinkmanual]", new AttributeRewriter("data-counterslinkmanual", base, workerOrigin));
  rewriter.on("img[src]",                   new AttributeRewriter("src",      base, workerOrigin));
  rewriter.on("img[srcset]",                new SrcsetRewriter("srcset",      base, workerOrigin));
  rewriter.on("img[data-src]",              new AttributeRewriter("data-src", base, workerOrigin));
  rewriter.on("img[data-lsrc]",             new AttributeRewriter("data-lsrc", base, workerOrigin));
  rewriter.on("source[src]",                new AttributeRewriter("src",      base, workerOrigin));
  rewriter.on("source[srcset]",             new SrcsetRewriter("srcset",      base, workerOrigin));
  rewriter.on("link[href]",                 new AttributeRewriter("href",     base, workerOrigin));
  rewriter.on("script[src]",                new ScriptRewriter("src",         base, workerOrigin, scriptBlocklist));
  rewriter.on("form[action]",               new AttributeRewriter("action",   base, workerOrigin));
  rewriter.on("iframe[src]",                new AttributeRewriter("src",      base, workerOrigin));

  // 术语注入：只在安全的文本元素中处理
  if (termRegex) {
    console.log("[TERM-READ] Setting up text handlers for term injection");
    
    // 明确列出要处理的文本元素（白名单模式）
    // 排除：script, style, noscript, code, pre, textarea, kbd, samp, title, alt属性等
    const textSelectors = [
      'p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'li', 'td', 'th', 'figcaption', 'caption', 'blockquote',
      'article', 'section', 'aside', 'header', 'footer', 'main',
      'em', 'strong', 'i', 'b', 'u', 'mark', 'small', 'del', 'ins',
      'sub', 'sup', 'time', 'label', 'summary', 'figcaption'
    ];
    
    // 为每个选择器注册文本处理器
    for (const selector of textSelectors) {
      rewriter.on(selector, {
        text(text) {
          termHandler.handleText(text);
        }
      });
    }
    
    console.log(`[TERM-READ] Registered text handlers for ${textSelectors.length} element types`);
    
  } else {
    console.log("[TERM-READ] No term regex, skipping text handlers");
  }
}

// 创建术语处理器
function createTermHandler(terms, regex) {
  if (!regex || !terms || terms.length === 0) {
    return {
      handleText(text) {
        // 不处理
      }
    };
  }

  // 创建术语到翻译的映射
  const termMap = new Map();
  for (const term of terms) {
    termMap.set(term.key, term.translation || "");
  }

  let matchCount = 0;

  return {
    handleText(text) {
      const content = text.text;
      if (!content || typeof content !== 'string') return;
      
      // 简单过滤：检查是否包含可能的大写或小写英文单词
      if (!/[a-zA-Z]{3,}/.test(content)) return;
      
      // 检查是否包含任何术语
      regex.lastIndex = 0;
      if (!regex.test(content)) return;
      
      // 重置并执行替换
      regex.lastIndex = 0;
      
      const replaced = content.replace(regex, (match) => {
        matchCount++;
        // 只保留 data-term，不显示 title 避免默认 tooltip
        // 翻译数据通过 data-term 后续从 KV 查询
        return `<span class="bio-term" data-term="${match}">${match}</span>`;
      });
      
      text.replace(replaced, { html: true });
      
      if (matchCount > 0 && matchCount <= 5) {
        console.log(`[TERM-READ] Injected ${matchCount} terms in text segment`);
      }
    }
  };
}
