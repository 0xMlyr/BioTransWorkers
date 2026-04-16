export const errorPage = (code, message) => `<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BioTrans — 错误</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0e0e0e;
    color: #c8c8c8;
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
    color: #3a3a3a;
    letter-spacing: 0.1em;
  }
  .message {
    margin-top: 1rem;
    font-size: 0.9rem;
    color: #666;
    letter-spacing: 0.05em;
  }
  .hint {
    margin-top: 2rem;
    font-size: 0.75rem;
    color: #3a3a3a;
  }
  .copyright {
    margin-top: 2rem;
    text-align: center;
    font-size: 0.7rem;
    color: #444;
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
  body {
    background: #0e0e0e;
    color: #fff;
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
    color: #888;
    letter-spacing: 0.1em;
  }
  .container {
    max-width: 700px;
    width: 100%;
  }
  h1 {
    font-size: 1.5rem;
    font-weight: 400;
    color: #fff;
    margin-bottom: 0.6rem;
    letter-spacing: 0.05em;
  }
  .badge {
    font-size: 0.75rem;
    color: #777;
    margin-bottom: 1.2rem;
  }
  .description {
    font-size: 0.85rem;
    line-height: 1.8;
    color: #aaa;
    margin-bottom: 1.5rem;
  }
  .input-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px solid rgba(255,255,255,0.3);
    padding-bottom: 6px;
    margin-bottom: 1.5rem;
  }
  input {
    flex: 1;
    background: transparent;
    border: none;
    color: #fff;
    font-family: inherit;
    font-size: 0.9rem;
    padding: 4px 0;
    outline: none;
  }
  input::placeholder { color: #555; }
  button {
    background: transparent;
    border: none;
    color: #888;
    font-family: inherit;
    font-size: 0.85rem;
    cursor: pointer;
    padding: 0;
    white-space: nowrap;
  }
  button:hover { color: #fff; }
  .supported-sites {
    margin-bottom: 1.5rem;
  }
  .supported-sites-title {
    font-size: 0.75rem;
    color: #666;
    margin-bottom: 0.8rem;
    letter-spacing: 0.05em;
  }
  .site-table {
    width: 100%;
    font-size: 0.8rem;
    border-collapse: collapse;
  }
  .site-table th {
    text-align: left;
    color: #555;
    font-weight: 400;
    padding: 0.4rem 0.6rem 0.4rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.1);
  }
  .site-table td {
    padding: 0.5rem 0.6rem 0.5rem 0;
    color: #aaa;
    border-bottom: 1px solid rgba(255,255,255,0.05);
  }
  .site-table td a {
    color: #aaa;
    text-decoration: none;
  }
  .site-table td a:hover { color: #fff; }
  .links {
    font-size: 0.8rem;
    margin-bottom: 0.4rem;
  }
  .links a {
    color: #666;
    text-decoration: none;
  }
  .links a:hover { color: #aaa; }
  .copyright {
    margin-top: 2rem;
    text-align: center;
    font-size: 0.7rem;
    color: #444;
    line-height: 1.6;
  }
</style>
</head>
<body>
  <div class="container">
    <h1>🪲🐛🦋<br>Bio-Trans</h1>
    <div class="badge">🚧 施工中...</div>
    <p class="description">这是专为昆虫形态学研究打造的网页术语翻译器，基于 Cloudflare Workers 边缘计算部署，代理诸如 ZooKeys 等目标网页并实现 HTMLRewriter 流式注入，为英文专业术语提供基于 KV 键值匹配的中文释义与悬停说明。</p>
    <div class="input-wrap">
      <input type="text" id="url-input" placeholder="https://">
      <button id="submit-btn">跳转 →</button>
    </div>
    <div class="supported-sites">
      <div class="supported-sites-title">已支持的网站</div>
      <table class="site-table">
        <tbody>
          <tr>
            <td><a href="https://www.mdpi.com" target="_blank" rel="noopener noreferrer">MDPI</a></td>
          </tr>
          <tr>
            <td><a href="https://plos.org" target="_blank" rel="noopener noreferrer">PLOS</a></td>
          </tr>
          <tr>
            <td><a href="https://zookeys.pensoft.net" target="_blank" rel="noopener noreferrer">ZooKeys</a></td>
          </tr>
          <tr>
            <td><a href="https://www.ncbi.nlm.nih.gov" target="_blank" rel="noopener noreferrer">NCBI</a></td>
          </tr>
          <tr>
            <td><a href="https://europeanjournaloftaxonomy.eu" target="_blank" rel="noopener noreferrer">EJT</a></td>
          </tr>
          <tr>
            <td><a href="https://www.mapress.com/zootaxa" target="_blank" rel="noopener noreferrer">Zootaxa</a></td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="links"><a href="https://github.com/0xMlyr/BioTransWorkers" target="_blank" rel="noopener noreferrer">Glossary</a></p>
    <p class="links"><a href="https://github.com/0xMlyr/BioTransWorkers" target="_blank" rel="noopener noreferrer">Github: 0xMlyr/BioTransWorkers</a></p>
    <div class="copyright">本网站不存储任何资源数据，代理内容版权归作者所有<br>Powered by MLYR Bio-Trans</div>
  </div>
  <script>
    (function() {
      function submit() {
        var url = document.getElementById('url-input').value.trim();
        if (url) {
          window.open('/?url=' + encodeURIComponent(url), '_blank');
        } else {
          alert('请输入目标 URL');
        }
      }
      document.getElementById('submit-btn').addEventListener('click', submit);
      document.getElementById('url-input').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') submit();
      });
    })();
  </script>
</body>
</html>`;
