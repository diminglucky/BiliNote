type AudioMetaLike = {
  cover_url?: unknown
  raw_info?: any
}

const apiBaseUrl = () => String(import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

const isHttpUrl = (value: string) => /^https?:\/\//i.test(value)

const isLocalAssetUrl = (value: string) =>
  value.startsWith('/static/') || value.startsWith('/uploads/') || value.startsWith('./')

const firstString = (value: unknown): string => {
  if (typeof value === 'string') return value.trim()
  return ''
}

const pushCandidate = (items: string[], value: unknown) => {
  const text = firstString(value)
  if (text) items.push(text)
}

export const resolveCoverUrl = (audioMeta?: AudioMetaLike | null): string => {
  if (!audioMeta) return ''

  const raw = audioMeta.raw_info || {}
  const candidates: string[] = []
  pushCandidate(candidates, audioMeta.cover_url)
  pushCandidate(candidates, raw.thumbnail)
  pushCandidate(candidates, raw.cover_url)
  pushCandidate(candidates, raw.coverUrl)
  pushCandidate(candidates, raw.cover)
  pushCandidate(candidates, raw.pic)
  pushCandidate(candidates, raw.image)
  pushCandidate(candidates, raw.thumbnail_url)

  if (Array.isArray(raw.thumbnails)) {
    raw.thumbnails.forEach((item: any) => pushCandidate(candidates, item?.url || item))
  }

  const nestedLists = [
    raw.aweme_detail?.video?.cover?.url_list,
    raw.aweme_detail?.video?.cover_original_scale?.url_list,
    raw.video?.cover?.url_list,
    raw.video?.cover_original_scale?.url_list,
  ]
  nestedLists.forEach(list => {
    if (Array.isArray(list)) list.forEach(item => pushCandidate(candidates, item))
  })

  return candidates.find(Boolean) || ''
}

export const extractFirstMarkdownImage = (markdown?: string): string => {
  if (!markdown) return ''

  const imagePattern = /!\[[^\]]*]\(\s*<?([^)\s>]+)>?(?:\s+["'][^"']*["'])?\s*\)/g
  let match = imagePattern.exec(markdown)
  while (match) {
    const url = match[1]?.trim()
    if (url && !url.startsWith('data:')) return url
    match = imagePattern.exec(markdown)
  }
  return ''
}

const proxiedImageSource = (rawUrl: string): string => {
  if (isHttpUrl(rawUrl) || rawUrl.startsWith('/')) {
    return `${apiBaseUrl()}/image_proxy?url=${encodeURIComponent(rawUrl)}`
  }
  return ''
}

const primaryImageSource = (rawUrl: string): string => {
  if (!rawUrl) return ''

  if (isLocalAssetUrl(rawUrl)) return [rawUrl]
  if (isHttpUrl(rawUrl)) return rawUrl
  if (rawUrl.startsWith('/')) return proxiedImageSource(rawUrl)
  return rawUrl
}

export const buildCoverImageSources = (
  audioMeta?: AudioMetaLike | null,
  markdown?: string,
): string[] => {
  const metaCover = resolveCoverUrl(audioMeta)
  const markdownCover = extractFirstMarkdownImage(markdown)
  const candidates = [
    primaryImageSource(metaCover),
    primaryImageSource(markdownCover),
    proxiedImageSource(metaCover),
    proxiedImageSource(markdownCover),
  ]

  return Array.from(new Set(candidates.filter(Boolean)))
}
