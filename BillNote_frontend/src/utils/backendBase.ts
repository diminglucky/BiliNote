function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '')
}

/**
 * 统一生成后端 API base：
 * - 未配置时走 `/api`（由 Vite 代理转发）
 * - 已配置绝对地址但未带 `/api` 时自动补齐
 * - 已带 `/api` 时保持不变
 */
export function getApiBase(rawBase?: string): string {
  const fallback = '/api'
  const raw = trimTrailingSlash((rawBase && rawBase.length > 0 ? rawBase : fallback).trim())

  if (raw === '/api' || raw.endsWith('/api')) return raw

  try {
    const url = new URL(raw)
    const pathname = trimTrailingSlash(url.pathname || '')
    url.pathname = `${pathname}/api`
    return trimTrailingSlash(url.toString())
  } catch {
    return `${raw}/api`
  }
}

