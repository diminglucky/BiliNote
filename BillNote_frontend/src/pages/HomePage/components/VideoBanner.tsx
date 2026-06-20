import { useEffect, useState } from 'react'
import { ExternalLink, ImageOff } from 'lucide-react'
import type { AudioMeta } from '@/store/taskStore'
import { buildCoverImageSources } from '@/utils/coverImage'

interface VideoBannerProps {
  audioMeta?: AudioMeta
  videoUrl?: string
  fallbackMarkdown?: string
}

const platformLabel: Record<string, string> = {
  bilibili: '哔哩哔哩',
  youtube: 'YouTube',
  douyin: '抖音',
  xiaohongshu: '小红书',
}

export default function VideoBanner({ audioMeta, videoUrl, fallbackMarkdown }: VideoBannerProps) {
  const [sourceIndex, setSourceIndex] = useState(0)
  const coverSources = buildCoverImageSources(audioMeta, fallbackMarkdown)
  const sourceKey = coverSources.join('\n')

  useEffect(() => {
    setSourceIndex(0)
  }, [sourceKey])

  if (!audioMeta) return null

  const coverUrl = coverSources[sourceIndex] || ''
  const title = audioMeta.title
  const uploader = audioMeta.raw_info?.uploader || ''
  const platform = platformLabel[audioMeta.platform] || audioMeta.platform || ''
  const originalUrl = videoUrl || audioMeta.raw_info?.webpage_url || ''

  return (
    <div className="mb-5 flex items-center gap-4 rounded-lg border border-neutral-200 bg-neutral-50 p-3">
      <div className="flex h-20 w-32 shrink-0 items-center justify-center overflow-hidden rounded-md border border-neutral-200 bg-white">
        {coverUrl ? (
          <img
            src={coverUrl}
            alt="视频封面"
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover"
            onError={() => setSourceIndex(index => index + 1)}
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 bg-neutral-100 text-neutral-400">
            <ImageOff className="h-4 w-4" />
            <span className="text-[11px]">无封面</span>
          </div>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <h2 className="truncate text-base font-semibold text-neutral-950" title={title}>
          {title}
        </h2>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
          {platform && (
            <span className="rounded-full border border-neutral-200 bg-white px-2 py-0.5 font-medium text-neutral-700">
              {platform}
            </span>
          )}
          {uploader && <span className="truncate">{uploader}</span>}
        </div>
      </div>

      {originalUrl && (
        <a
          href={originalUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex shrink-0 items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-3 py-2 text-xs font-medium text-neutral-700 transition hover:border-neutral-300 hover:bg-neutral-100"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          <span>原视频</span>
        </a>
      )}
    </div>
  )
}
