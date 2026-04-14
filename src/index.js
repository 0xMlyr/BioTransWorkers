export default {
  // 当有人访问你的 Worker 网址时，这个 fetch 函数就会被触发
  async fetch(request, env, ctx) {
    // 这是一个简单的后端逻辑：返回一段文字
    return new Response("BioTransWorkers 后端已成功运行！", {
      headers: { "content-type": "text/plain;charset=UTF-8" },
    });
  },
};