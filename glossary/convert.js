const fs = require("fs");
const path = require("path");

const lines = fs.readFileSync(path.join(__dirname, "glossary.txt"), "utf-8").split(/\r?\n/);

const seen = new Set();
const result = [];

for (const line of lines) {
  const trimmed = line.trim();
  if (!trimmed) continue;

  const spaceIdx = trimmed.indexOf(" ");
  if (spaceIdx === -1) continue;

  const key = trimmed.slice(0, spaceIdx);
  const translation = trimmed.slice(spaceIdx + 1).trim();

  if (seen.has(key)) continue;
  seen.add(key);

  result.push({
    key,
    value: JSON.stringify({ translation, phonetic: "/null/" }),
  });
}

fs.writeFileSync(path.join(__dirname, "glossary.json"), JSON.stringify(result, null, 2), "utf-8");
console.log(`转换完成，共 ${result.length} 条术语`);
