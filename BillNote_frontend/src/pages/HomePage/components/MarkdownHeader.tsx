'use client'

import { useEffect, useState } from 'react'
import { Copy, Download, MessageSquare } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface VersionNote {
  ver_id: string
  model_name?: string
  style?: string
  created_at?: string
}

interface NoteHeaderProps {
  currentTask?: {
    markdown: VersionNote[]
  }
  isMultiVersion: boolean
  currentVerId: string
  setCurrentVerId: (id: string) => void
  modelName: string
  style: string
  noteStyles: { value: string; label: string }[]
  onCopy: () => void
  onDownload: () => void
  isExporting?: boolean
  createAt?: string | Date
  setShowTranscribe: (show: boolean) => void
  showTranscribe: boolean
  showChat?: false | 'half' | 'full'
  setShowChat?: (mode: false | 'half' | 'full') => void
  viewMode: 'map' | 'preview'
  setViewMode: (mode: 'map' | 'preview') => void
  isTaskRunning?: boolean
  taskStatus?: string
  visualSummary?: string
}

export function MarkdownHeader({
  currentTask,
  isMultiVersion,
  currentVerId,
  setCurrentVerId,
  modelName,
  style,
  noteStyles,
  onCopy,
  onDownload,
  isExporting,
  createAt,
  showTranscribe,
  setShowTranscribe,
  showChat,
  setShowChat,
  viewMode,
  setViewMode,
  isTaskRunning,
  taskStatus,
  visualSummary,
}: NoteHeaderProps) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let timer: NodeJS.Timeout
    if (copied) {
      timer = setTimeout(() => setCopied(false), 2000)
    }
    return () => clearTimeout(timer)
  }, [copied])

  const handleCopy = () => {
    onCopy()
    setCopied(true)
  }

  const styleName = noteStyles.find(v => v.value === style)?.label || style

  const formatDate = (date: string | Date | undefined) => {
    if (!date) return ''
    const d = typeof date === 'string' ? new Date(date) : date
    if (isNaN(d.getTime())) return ''
    return d
      .toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
      .replace(/\//g, '-')
  }

  return (
    <div className="sticky top-0 z-10 border-b bg-white/95 backdrop-blur-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {isMultiVersion && (
              <Select value={currentVerId} onValueChange={setCurrentVerId}>
                <SelectTrigger className="h-8 w-[160px] text-sm">
                  <div className="flex items-center">
                    {(() => {
                      const idx = currentTask?.markdown.findIndex(v => v.ver_id === currentVerId)
                      return idx !== -1 ? `版本（${currentVerId.slice(-6)}）` : ''
                    })()}
                  </div>
                </SelectTrigger>

                <SelectContent>
                  {(currentTask?.markdown || []).map(v => {
                    const shortId = v.ver_id.slice(-6)
                    return (
                      <SelectItem key={v.ver_id} value={v.ver_id}>
                        {`版本（${shortId}）`}
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
            )}

            <Badge variant="secondary" className="border border-neutral-200 bg-neutral-100 text-neutral-700 hover:bg-neutral-200">
              {modelName}
            </Badge>
            <Badge variant="secondary" className="border border-neutral-200 bg-white text-neutral-700 hover:bg-neutral-100">
              {styleName}
            </Badge>
            {createAt && <div className="text-sm text-neutral-500">创建时间 {formatDate(createAt)}</div>}
            {isTaskRunning && (
              <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-700">
                {taskStatus === 'ENHANCING' ? '截图增强中' : '重新生成中'}
              </Badge>
            )}
            {taskStatus === 'PARTIAL_SUCCESS' && (
              <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-700">
                已完成，部分截图跳过
              </Badge>
            )}
            {visualSummary && (
              <Badge variant="outline" className="border-neutral-200 bg-white text-neutral-700">
                {visualSummary}
              </Badge>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Tabs value={viewMode} onValueChange={v => setViewMode(v as 'map' | 'preview')}>
            <TabsList className="h-9 w-auto">
              <TabsTrigger value="preview" className="h-8 px-3 text-xs">
                Markdown
              </TabsTrigger>
              <TabsTrigger value="map" className="h-8 px-3 text-xs">
                思维导图
              </TabsTrigger>
            </TabsList>
          </Tabs>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button onClick={handleCopy} variant="ghost" size="sm" className="h-8 px-2">
                <Copy className="mr-1.5 h-4 w-4" />
                <span className="text-sm">{copied ? '已复制' : '复制'}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>复制内容</TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                onClick={onDownload}
                variant="ghost"
                size="sm"
                className="h-8 px-2"
                disabled={isExporting}
              >
                <Download className="mr-1.5 h-4 w-4" />
                <span className="text-sm">{isExporting ? '打包中' : '导出笔记'}</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>下载为 Markdown 图片包，含普通版和内嵌版</TooltipContent>
          </Tooltip>
        </TooltipProvider>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                onClick={() => {
                  setShowTranscribe(!showTranscribe)
                }}
                variant={showTranscribe ? 'default' : 'ghost'}
                size="sm"
                className="h-8 px-2"
              >
                <span className="text-sm">原文</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>原文参照</TooltipContent>
          </Tooltip>
        </TooltipProvider>
        {setShowChat && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  onClick={() => setShowChat(showChat ? false : 'half')}
                  variant={showChat ? 'default' : 'ghost'}
                  size="sm"
                  className="h-8 px-2"
                >
                  <MessageSquare className="mr-1.5 h-4 w-4" />
                  <span className="text-sm">问答</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>基于笔记内容的 AI 问答</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
        </div>
      </div>
    </div>
  )
}
