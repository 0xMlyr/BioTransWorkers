export const pensoftConfig = {
  phpRetry: true,
  scriptBlocklist: [
    /cdnjs\.cloudflare\.com\/ajax\/libs\/mathjax/i,
  ],
  // Phase1：术语注入范围（iframe 内正文）
  termInjectionScope: "iframe#articleIframe",
};
