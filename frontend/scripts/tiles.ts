// Prepares a flat directory of <layer>__<map>.pmtiles files for the site, with an
// index.json listing them, so the map knows which maps exist (src/lib/catalog.ts).
//
//   bun scripts/tiles.ts index <dir>        write <dir>/index.json (Deploy workflow)
//   bun scripts/tiles.ts stage <src> <dir>  link pipeline output <src>/<layer>/<map>.pmtiles
//                                           into <dir> under its Release name, then index it
import {
  copyFileSync,
  linkSync,
  mkdirSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import path from "node:path"

function index(dir: string): number {
  const files = readdirSync(dir)
    .filter((file) => file.endsWith(".pmtiles"))
    .sort()
  writeFileSync(
    path.join(dir, "index.json"),
    `${JSON.stringify(files, null, 1)}\n`
  )
  return files.length
}

function stage(src: string, dir: string): void {
  rmSync(dir, { recursive: true, force: true })
  mkdirSync(dir, { recursive: true })
  for (const layer of readdirSync(src, { withFileTypes: true })) {
    if (!layer.isDirectory()) continue
    for (const file of readdirSync(path.join(src, layer.name))) {
      if (!file.endsWith(".pmtiles")) continue
      const from = path.join(src, layer.name, file)
      const to = path.join(dir, `${layer.name}__${file}`)
      try {
        linkSync(from, to)
      } catch {
        copyFileSync(from, to)
      }
    }
  }
}

const [command, ...args] = process.argv.slice(2)
if (command === "index" && args.length === 1) {
  console.log(`Indexed ${index(args[0])} PMTiles files in ${args[0]}`)
} else if (command === "stage" && args.length === 2) {
  stage(args[0], args[1])
  console.log(
    `Staged ${index(args[1])} PMTiles files from ${args[0]} in ${args[1]}`
  )
} else {
  console.error("usage: bun scripts/tiles.ts index <dir> | stage <src> <dir>")
  process.exit(1)
}
