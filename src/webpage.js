export const errorPage = (code, message) => `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BioTrans — 错误</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #1a1a1a;
    color: #e0e0e0;
    font-family: 'SF Mono', 'Fira Code', monospace;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .container {
    text-align: center;
    padding: 2rem;
  }
  .code {
    font-size: 4rem;
    font-weight: 700;
    color: #2e7d32;
    letter-spacing: 0.1em;
  }
  .message {
    margin-top: 1rem;
    font-size: 0.9rem;
    color: #999;
    letter-spacing: 0.05em;
  }
  .hint {
    margin-top: 2rem;
    font-size: 0.75rem;
    color: #2e7d32;
  }
  .copyright {
    margin-top: 2rem;
    text-align: center;
    font-size: 0.7rem;
    color: #999;
    line-height: 1.6;
  }
</style>
</head>
<body>
  <div class="container">
    <div class="code">${code}</div>
    <div class="message">${message}</div>
    <div class="hint">biotrans.mlyr.top/?url=https://example.com/paper</div>
    <div class="copyright">本网站不存储任何资源数据，代理内容版权归作者所有<br>Powered by MLYR Bio-Trans</div>
  </div>
</body>
</html>`;

export const landingPage = () => `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bio-Trans</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #1a1a1a;
    --text: #e0e0e0;
    --text-secondary: #999;
    --accent: #4caf50;
    --border: #333;
    --input-border: #4caf50;
    --table-border: #2a2a2a;
    --hover-bg: rgba(76,175,80,0.05);
  }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'SF Mono', 'Fira Code', monospace;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 2rem;
  }
  .brand {
    position: absolute;
    top: 2rem;
    right: 2rem;
    font-size: 0.9rem;
    color: var(--accent);
    letter-spacing: 0.1em;
  }
  .container {
    max-width: 700px;
    width: 100%;
  }
  h1 {
    font-size: 1.5rem;
    font-weight: 400;
    color: var(--text);
    margin-bottom: 0.6rem;
    letter-spacing: 0.05em;
  }
  .badge {
    font-size: 0.75rem;
    color: var(--accent);
    margin-bottom: 1.2rem;
  }
  .description {
    font-size: 0.85rem;
    line-height: 1.8;
    color: var(--text-secondary);
    margin-bottom: 1.5rem;
  }
  .input-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 2px solid var(--input-border);
    padding-bottom: 6px;
    margin-bottom: 1.5rem;
  }
  input {
    flex: 1;
    background: transparent;
    border: none;
    color: var(--text);
    font-family: inherit;
    font-size: 0.9rem;
    padding: 4px 0;
    outline: none;
  }
  input::placeholder { color: var(--text-secondary); }
  button {
    background: transparent;
    border: none;
    color: var(--accent);
    font-family: inherit;
    font-size: 0.85rem;
    cursor: pointer;
    padding: 0;
    white-space: nowrap;
  }
  button:hover { opacity: 0.8; }
  .drawer-container {
    margin-bottom: 1.5rem;
  }
  .drawer-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.6rem 0;
    cursor: pointer;
    border-bottom: 1px solid var(--border);
    transition: background 0.2s ease;
  }
  .drawer-item:hover {
    background: var(--hover-bg);
  }
  .drawer-item:first-child {
    border-top: 1px solid var(--border);
  }
  .drawer-title {
    font-size: 0.75rem;
    color: var(--text-secondary);
    letter-spacing: 0.05em;
  }
  .drawer-arrow {
    font-size: 0.7rem;
    color: var(--text-secondary);
    transition: transform 0.3s ease;
  }
  .drawer-item.expanded .drawer-arrow {
    transform: rotate(180deg);
  }
  .drawer-content {
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.3s ease, padding 0.3s ease;
    padding: 0 0.5rem;
  }
  .drawer-content.expanded {
    max-height: 500px;
    padding: 0.5rem;
  }
  .site-table {
    width: 100%;
    font-size: 0.8rem;
    border-collapse: collapse;
  }
  .site-table th {
    text-align: left;
    color: var(--text);
    font-weight: 400;
    padding: 0.4rem 0.6rem 0.4rem 0;
    border-bottom: 1px solid var(--border);
  }
  .site-table td {
    padding: 0.5rem 0.6rem 0.5rem 0;
    color: var(--text-secondary);
    border-bottom: 1px solid var(--table-border);
  }
  .site-table td a {
    color: var(--accent);
    text-decoration: none;
  }
  .site-table td a:hover { opacity: 0.8; }
  .links {
    font-size: 0.8rem;
    margin-bottom: 0.4rem;
  }
  .links a {
    color: var(--text-secondary);
    text-decoration: none;
  }
  .links a:hover { color: var(--accent); }
  .copyright {
    margin-top: 2rem;
    text-align: center;
    font-size: 0.7rem;
    color: var(--text-secondary);
    line-height: 1.6;
  }
</style>
</head>
<body>
  <div class="brand">Bio-Trans</div>
  <div class="container">
    <h1>🪲🐛🦋<br>Bio-Trans</h1>
    <div class="badge">🚧 施工中...</div>
    <p class="description">这是专为昆虫形态学研究打造的网页术语翻译器，基于 Cloudflare Workers 边缘计算部署，代理诸如 ZooKeys 等目标网页并实现 HTMLRewriter 流式注入，为英文专业术语提供基于 KV 键值匹配的中文释义与悬停说明。</p>
    <div class="input-wrap">
      <input type="text" id="url-input" placeholder="https://">
      <button id="submit-btn">跳转 →</button>
    </div>
    <div class="drawer-container">
      <div class="drawer-item" data-drawer="sites">
        <span class="drawer-title">已支持的网站</span>
        <span class="drawer-arrow">▼</span>
      </div>
      <div class="drawer-content" id="drawer-sites">
        <table class="site-table">
          <tbody>
            <tr><td><a href="https://www.mdpi.com" target="_blank" rel="noopener noreferrer">MDPI</a></td></tr>
            <tr><td><a href="https://plos.org" target="_blank" rel="noopener noreferrer">PLOS</a></td></tr>
            <tr><td><a href="https://zookeys.pensoft.net" target="_blank" rel="noopener noreferrer">ZooKeys</a></td></tr>
            <tr><td><a href="https://www.ncbi.nlm.nih.gov" target="_blank" rel="noopener noreferrer">NCBI</a></td></tr>
            <tr><td><a href="https://europeanjournaloftaxonomy.eu" target="_blank" rel="noopener noreferrer">EJT</a></td></tr>
            <tr><td><a href="https://www.mapress.com/zootaxa" target="_blank" rel="noopener noreferrer">Zootaxa</a></td></tr>
          </tbody>
        </table>
      </div>
      <div class="drawer-item" data-drawer="glossaries">
        <span class="drawer-title">已支持的术语表</span>
        <span class="drawer-arrow">▼</span>
      </div>
      <div class="drawer-content" id="drawer-glossaries">
        <table class="site-table">
          <tbody>
            <tr><td><a href="https://github.com/hymao/HAO" target="_blank" rel="noopener noreferrer">HAO - Hymenoptera Anatomy Ontology</a></td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <p class="links"><a href="https://github.com/0xMlyr/BioTransWorkers" target="_blank" rel="noopener noreferrer">Github: 0xMlyr/BioTransWorkers</a></p>
    <div class="copyright">本网站不存储任何资源数据，代理内容版权归作者所有<br>Powered by MLYR Bio-Trans</div>
  </div>
  <script>
    (function() {
      // URL 跳转功能
      function submit() {
        var url = document.getElementById('url-input').value.trim();
        if (!url) {
          alert('请输入目标 URL');
          return;
        }
        // 自动补全协议（如果没有 http:// 或 https://）
        var hasProtocol = url.indexOf('http://') === 0 || url.indexOf('https://') === 0;
        if (!hasProtocol) {
          url = 'https://' + url;
        }
        window.open('/?url=' + encodeURIComponent(url), '_blank');
      }
      document.getElementById('submit-btn').addEventListener('click', submit);
      document.getElementById('url-input').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') submit();
      });

      // 抽屉交互
      var drawerItems = document.querySelectorAll('.drawer-item');
      drawerItems.forEach(function(item) {
        item.addEventListener('click', function() {
          var drawerId = this.getAttribute('data-drawer');
          var content = document.getElementById('drawer-' + drawerId);
          // 切换当前抽屉状态
          this.classList.toggle('expanded');
          content.classList.toggle('expanded');
        });
      });
    })();
  </script>
</body>
</html>`;
