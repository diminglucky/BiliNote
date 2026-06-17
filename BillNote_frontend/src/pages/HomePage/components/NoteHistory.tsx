import { useTaskStore } from '@/store/taskStore'
import { cn } from '@/lib/utils.ts'
import { Search, Trash } from 'lucide-react'
import { Button } from '@/components/ui/button.tsx'
import Fuse from 'fuse.js'

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip.tsx'
import LazyImage from '@/components/LazyImage.tsx'
import { FC, useEffect, useMemo, useState } from 'react'
import { isFailedTaskStatus, isRunningTaskStatus, isSuccessTaskStatus } from '@/models/taskStateMachine'

interface NoteHistoryProps {
  onSelect: (taskId: string) => void
  selectedId: string | null
}

const NoteHistory: FC<NoteHistoryProps> = ({ onSelect, selectedId }) => {
  const tasks = useTaskStore(state => state.tasks)
  const removeTask = useTaskStore(state => state.removeTask)
  const baseURL = (String(import.meta.env.VITE_API_BASE_URL || 'api')).replace(/\/$/, '')
  const [rawSearch, setRawSearch] = useState('')
  const [search, setSearch] = useState('')
  const fuse = useMemo(() => new Fuse(tasks, {
    keys: ['audioMeta.title'],
    threshold: 0.4,
  }), [tasks])
  useEffect(() => {
    const timer = setTimeout(() => {
      if (rawSearch === '') return
      setSearch(rawSearch)
    }, 300) // 300ms 防抖

    return () => clearTimeout(timer)
  }, [rawSearch])
  const filteredTasks = search.trim()
      ? fuse.search(search).map(result => result.item)
      : tasks
  if (filteredTasks.length === 0) {
    return (
      <>
        <div className="relative mb-3">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
          <input
            type="text"
            placeholder="搜索笔记标题"
            className="h-10 w-full rounded-md border border-neutral-200 bg-neutral-50 pl-9 pr-3 text-sm outline-none transition focus:border-neutral-400 focus:bg-white"
            value={rawSearch}
            onChange={e => {
              setRawSearch(e.target.value)
              if (e.target.value === '') setSearch('')
            }}
          />
        </div>
        <div className="rounded-lg border border-dashed border-neutral-300 bg-neutral-50 px-4 py-8 text-center">
          <p className="text-sm font-medium text-neutral-700">还没有匹配的笔记</p>
          <p className="mt-1 text-xs text-neutral-500">提交视频后会在这里沉淀成你的知识库</p>
        </div>
      </>

    )
  }


  return (
    <>
      <div className="mb-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" />
          <input
            type="text"
            placeholder="搜索笔记标题"
            className="h-10 w-full rounded-md border border-neutral-200 bg-neutral-50 pl-9 pr-3 text-sm outline-none transition focus:border-neutral-400 focus:bg-white"
            value={rawSearch}
            onChange={e => {
              setRawSearch(e.target.value)
              if (e.target.value === '') setSearch('')
            }}
          />
        </div>
      </div>
      <div className="flex flex-col gap-1.5 overflow-hidden">
        {filteredTasks.map(task => (
          <div
            key={task.id}
            onClick={() => onSelect(task.id)}
            className={cn(
              'group flex cursor-pointer flex-col rounded-md border border-transparent bg-white px-2.5 py-2 transition hover:border-neutral-200 hover:bg-neutral-50',
              selectedId === task.id && 'border-neutral-300 bg-neutral-100 hover:bg-neutral-100'
            )}
          >
            <div className="flex items-center gap-3">
              {task.platform === 'local' ? (
                <img
                  src={
                    task.audioMeta.cover_url ? `${task.audioMeta.cover_url}` : '/placeholder.png'
                  }
                  alt="封面"
                  className="h-11 w-16 rounded-md object-cover"
                />
              ) : (
                <LazyImage
                  src={
                    task.audioMeta.cover_url
                      ? `${baseURL}/image_proxy?url=${encodeURIComponent(task.audioMeta.cover_url)}`
                      : '/placeholder.png'
                  }
                  alt="封面"
                />
              )}

              <div className="min-w-0 flex-1">
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className={cn(
                        'line-clamp-2 overflow-hidden text-sm font-medium leading-5 text-ellipsis',
                        selectedId === task.id ? 'text-neutral-950' : 'text-neutral-900'
                      )}>
                        {task.audioMeta.title || '未命名笔记'}
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{task.audioMeta.title || '未命名笔记'}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
            <div className="mt-2 flex items-center justify-between pl-[4.75rem] text-[10px]">
              <div className="shrink-0">
                {isSuccessTaskStatus(task.status) && (
                  <div className="rounded-full bg-emerald-100 px-2 py-0.5 text-center font-medium text-emerald-700">
                    已完成
                  </div>
                )}
                {isRunningTaskStatus(task.status) ? (
                  <div className="rounded-full bg-amber-100 px-2 py-0.5 text-center font-medium text-amber-700">
                    处理中
                  </div>
                ) : (
                  <></>
                )}
                {isFailedTaskStatus(task.status) && (
                  <div className="rounded-full bg-red-100 px-2 py-0.5 text-center font-medium text-red-700">失败</div>
                )}
              </div>

              <div>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={e => {
                          e.stopPropagation()
                          removeTask(task.id)
                        }}
                        className="h-7 w-7 shrink-0 rounded-md p-0 text-neutral-500 hover:bg-neutral-200 hover:text-neutral-950"
                      >
                        <Trash className="h-4 w-4" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>删除</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

export default NoteHistory
