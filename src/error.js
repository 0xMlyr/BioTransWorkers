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
</style>
</head>
<body>
  <div class="container">
    <div class="code">${code}</div>
    <div class="message">${message}</div>
    <div class="hint">biotrans.mlyr.top/?url=https://example.com/paper</div>
  </div>
</body>
</html>`;
