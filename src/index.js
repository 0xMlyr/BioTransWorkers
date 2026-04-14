export default {
  async fetch(request, env, ctx) {
    return new Response("BioTransWorkers 后端已成功运行！", {
      headers: { "content-type": "text/plain;charset=UTF-8" },
    });
  },
};