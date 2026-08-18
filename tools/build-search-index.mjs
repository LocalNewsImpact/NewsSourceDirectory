/**
 * Build a prebuilt MiniSearch index from the published sites.json.
 *
 * The index is generated in Node rather than Python on purpose: MiniSearch's
 * serialised form is an internal detail of the library, and reimplementing it
 * server-side would silently rot on the next version bump. Here it is produced
 * by the same library version the widget loads, pinned in package.json.
 *
 *   node tools/build-search-index.mjs dist/feed
 *
 * Reads manifest.json, indexes the sites file it names, writes a content-hashed
 * index beside it and adds it to the manifest.
 */

import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import MiniSearch from 'minisearch'

// Fields the widget searches, and the fields it needs back without a second lookup.
export const SEARCH_FIELDS = ['outlet_name', 'domain', 'cities', 'counties', 'states', 'source_files']
export const STORE_FIELDS = ['outlet_name', 'domain']

export const SEARCH_OPTIONS = {
  idField: 'outlet_id',
  fields: SEARCH_FIELDS,
  storeFields: STORE_FIELDS,
  searchOptions: {
    prefix: true,
    fuzzy: 0.2,
    // An outlet's own name should outrank a coincidental county match.
    boost: { outlet_name: 3, domain: 2 },
  },
}

const canonical = (value) => JSON.stringify(value)
const sha256 = (text) => createHash('sha256').update(text).digest('hex')

function build(dir) {
  const manifestPath = join(dir, 'manifest.json')
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))

  const sitesPath = join(dir, manifest.files.sites.path)
  const sites = JSON.parse(readFileSync(sitesPath, 'utf8'))

  const mini = new MiniSearch(SEARCH_OPTIONS)
  mini.addAll(sites)

  const serialised = canonical(mini)
  const sha = sha256(serialised)
  const name = `search-index.${sha.slice(0, 8)}.json`
  writeFileSync(join(dir, name), serialised)

  manifest.files.search_index = {
    path: name,
    sha256: sha,
    bytes: Buffer.byteLength(serialised),
    fields: SEARCH_FIELDS,
    store_fields: STORE_FIELDS,
  }
  // Match the Python writer: sorted keys, no spaces, so hashes stay comparable.
  writeFileSync(manifestPath, JSON.stringify(sortKeys(manifest)))

  return { documents: sites.length, name, bytes: manifest.files.search_index.bytes }
}

function sortKeys(value) {
  if (Array.isArray(value)) return value.map(sortKeys)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map((k) => [k, sortKeys(value[k])]))
  }
  return value
}

const dir = process.argv[2] || 'dist/feed'
const result = build(dir)
console.log(`indexed ${result.documents} documents -> ${dir}/${result.name} (${(result.bytes / 1024).toFixed(1)}KB)`)
