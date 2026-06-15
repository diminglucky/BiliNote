import React, { FC, useRef, useState } from 'react'
import {
  Library,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Sparkles,
  X,
} from 'lucide-react'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip.tsx'
import { Link } from 'react-router-dom'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { ScrollArea } from '@/components/ui/scroll-area.tsx'
import type { ImperativePanelHandle } from 'react-resizable-panels'
import logo from '@/assets/icon.svg'

interface IProps {
  NoteForm: React.ReactNode
  Preview: React.ReactNode
  History: React.ReactNode
}

const IconButton = ({
  label,
  children,
  onClick,
}: {
  label: string
  children: React.ReactNode
  onClick?: () => void
}) => (
  <TooltipProvider>
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          onClick={onClick}
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-neutral-200 bg-white text-neutral-500 shadow-sm transition hover:border-neutral-300 hover:bg-neutral-50 hover:text-neutral-950"
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  </TooltipProvider>
)

const HomeLayout: FC<IProps> = ({ NoteForm, Preview, History }) => {
  const [isLeftCollapsed, setIsLeftCollapsed] = useState(false)
  const [isHistoryOpen, setIsHistoryOpen] = useState(false)
  const leftPanelRef = useRef<ImperativePanelHandle>(null)

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-neutral-100 text-neutral-950">
      <header className="flex h-[60px] shrink-0 items-center justify-between border-b border-neutral-200 bg-white/90 px-5 backdrop-blur">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg border border-neutral-200 bg-white">
            <img src={logo} alt="VideoNote" className="h-full w-full object-contain" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-lg font-semibold text-neutral-950">VideoNote</h1>
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                Studio
              </span>
            </div>
            <p className="truncate text-xs text-neutral-500">
              从视频、转写和关键画面生成可复用的学习笔记
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="hidden items-center gap-2 rounded-md border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-xs text-neutral-600 md:flex">
            <Sparkles className="h-3.5 w-3.5 text-amber-600" />
            图文增强工作流
          </div>
          <IconButton label="打开笔记库" onClick={() => setIsHistoryOpen(true)}>
            <Library className="h-4 w-4" />
          </IconButton>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Link
                  to="/settings"
                  aria-label="设置"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-neutral-200 bg-white text-neutral-600 shadow-sm transition hover:border-neutral-300 hover:bg-neutral-50 hover:text-neutral-950"
                >
                  <Settings className="h-4 w-4" />
                </Link>
              </TooltipTrigger>
              <TooltipContent>设置</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </header>

      <ResizablePanelGroup direction="horizontal" className="relative min-h-0 flex-1 p-3">
        <ResizablePanel
          ref={leftPanelRef}
          defaultSize={28}
          minSize={22}
          maxSize={36}
          collapsible
          collapsedSize={0}
          onCollapse={() => setIsLeftCollapsed(true)}
          onExpand={() => setIsLeftCollapsed(false)}
        >
          <aside className="flex h-full flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white">
            <div className="flex h-[52px] shrink-0 items-center justify-between border-b border-neutral-100 px-4">
              <div>
                <div className="text-sm font-semibold text-neutral-950">生成工作流</div>
                <div className="text-xs text-neutral-500">视频、模型、视觉和输出</div>
              </div>
              <IconButton label="收起生成控制台" onClick={() => leftPanelRef.current?.collapse()}>
                <PanelLeftClose className="h-4 w-4" />
              </IconButton>
            </div>
            <ScrollArea className="min-h-0 flex-1">
              <div className="p-3">{NoteForm}</div>
            </ScrollArea>
          </aside>
        </ResizablePanel>

        <ResizableHandle className="mx-2 w-1 rounded-full bg-transparent transition hover:bg-neutral-300" />

        {isLeftCollapsed && (
          <button
            type="button"
            onClick={() => leftPanelRef.current?.expand()}
            className="mr-2 flex h-full w-9 shrink-0 items-center justify-center rounded-lg border border-neutral-200 bg-white text-neutral-500 shadow-sm transition hover:bg-neutral-50 hover:text-neutral-950"
            aria-label="展开生成控制台"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        )}

        <ResizablePanel defaultSize={72} minSize={48}>
          <main className="h-full overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm">
            {Preview}
          </main>
        </ResizablePanel>

        {isHistoryOpen && (
          <div className="absolute inset-3 z-30 flex justify-end">
            <button
              type="button"
              aria-label="关闭笔记库遮罩"
              className="absolute inset-0 bg-neutral-950/10 backdrop-blur-[1px]"
              onClick={() => setIsHistoryOpen(false)}
            />
            <aside className="relative z-10 flex h-full w-[360px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-xl">
              <div className="flex h-[52px] shrink-0 items-center justify-between border-b border-neutral-100 px-4">
                <div className="flex items-center gap-2">
                  <Library className="h-4 w-4 text-neutral-500" />
                  <div>
                    <div className="text-sm font-semibold text-neutral-950">笔记库</div>
                    <div className="text-xs text-neutral-500">历史任务与版本入口</div>
                  </div>
                </div>
                <IconButton label="关闭笔记库" onClick={() => setIsHistoryOpen(false)}>
                  <X className="h-4 w-4" />
                </IconButton>
              </div>
              <ScrollArea className="min-h-0 flex-1">
                <div className="p-3">{History}</div>
              </ScrollArea>
            </aside>
          </div>
        )}
      </ResizablePanelGroup>
    </div>
  )
}

export default HomeLayout
