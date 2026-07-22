import { apiFetch } from '@/lib/utils'

type CacheEntry<T> = {
  value: T | null
  promise: Promise<T> | null
  expiresAt: number
}

function createCacheEntry<T>(): CacheEntry<T> {
  return {
    value: null,
    promise: null,
    expiresAt: 0,
  }
}

function loadCached<T>(
  entry: CacheEntry<T>,
  loader: () => Promise<T>,
  options: {
    force?: boolean
    ttlMs?: number
  } = {},
): Promise<T> {
  const force = Boolean(options.force)
  const ttlMs = options.ttlMs ?? 30_000
  const now = Date.now()
  if (!force && entry.value !== null && entry.expiresAt > now) {
    return Promise.resolve(entry.value)
  }
  if (!force && entry.promise) {
    return entry.promise
  }
  const pending = loader()
    .then((value) => {
      entry.value = value
      entry.expiresAt = Date.now() + ttlMs
      entry.promise = null
      return value
    })
    .catch((error) => {
      entry.promise = null
      throw error
    })
  entry.promise = pending
  return pending
}

const platformsCache = createCacheEntry<any[]>()
const configCache = createCacheEntry<Record<string, any>>()
const configOptionsCache = createCacheEntry<any>()

export function invalidatePlatformsCache() {
  platformsCache.value = null
  platformsCache.promise = null
  platformsCache.expiresAt = 0
}

export function invalidateConfigCache() {
  configCache.value = null
  configCache.promise = null
  configCache.expiresAt = 0
}

export function invalidateConfigOptionsCache() {
  configOptionsCache.value = null
  configOptionsCache.promise = null
  configOptionsCache.expiresAt = 0
}

export function invalidateAppDataCaches() {
  invalidatePlatformsCache()
  invalidateConfigCache()
  invalidateConfigOptionsCache()
}

export function getPlatforms(options?: { force?: boolean }) {
  return loadCached(platformsCache, async () => {
    const data = await apiFetch('/platforms')
    return Array.isArray(data) ? data : []
  }, { force: options?.force })
}

export function getConfig(options?: { force?: boolean }) {
  return loadCached(configCache, async () => {
    const data = await apiFetch('/config')
    return data && typeof data === 'object' ? data : {}
  }, { force: options?.force })
}

export function getConfigOptions(options?: { force?: boolean }) {
  return loadCached(configOptionsCache, async () => {
    return apiFetch('/config/options')
  }, { force: options?.force })
}
